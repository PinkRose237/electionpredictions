import Foundation
import Observation

/// Everything on screen: site data (races, chamber baselines, poll-closing times), merged results, and
/// the refresh loop. Results come from the live feeds with the site's manual overrides (results.json) on
/// top; if the feeds are unreachable it falls back to the site's saved snapshot (results-auto.json).
@MainActor @Observable
final class ResultsStore {
    /// Results trickle in for days after election night: every five minutes is plenty.
    static let interval: TimeInterval = 5 * 60

    private(set) var races: [String: Race] = [:]
    private(set) var summary: SiteSummary?
    private(set) var closeTimes: [String: Date] = [:]
    private(set) var results: [String: ResultEntry] = [:]

    private(set) var source: String?          // "AP via NYT", "CNN", "saved snapshot", "demo"
    private(set) var lastUpdate: Date?
    private(set) var nextUpdate: Date?
    private(set) var problem: String?
    private(set) var loading = true

    let demo = UserDefaults.standard.bool(forKey: "DemoMode") || ProcessInfo.processInfo.arguments.contains("-demo")
    private var demoStep = 0
    private var loop: Task<Void, Never>?
    private var siteLoadedAt: Date?

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                // A refresh that couldn't load the site leaves no future time set: retry in a minute.
                let wait = await self?.nextUpdate?.timeIntervalSinceNow ?? 0
                try? await Task.sleep(for: .seconds(wait > 1 ? wait : 60))
            }
        }
    }

    func refreshNow() {
        loop?.cancel()
        loop = nil
        start()
    }

    func refresh() async {
        if siteLoadedAt == nil || Date().timeIntervalSince(siteLoadedAt!) > 1800 { await loadSite() }
        guard !races.isEmpty else { loading = false; return }
        let list = Array(races.values)
        async let liveTask = demo ? Feeds.LiveResult() : Feeds.fetchLive(races: list)
        async let manualTask = Feeds.siteFile("results.json", as: ResultsFile.self)
        async let callsTask = Feeds.siteFile("calls.json", as: CallsFile.self)
        let (live, manual, outletCalls) = await (liveTask, manualTask, callsTask)

        var base = live.races
        if demo {
            demoStep += 1
            base = DemoData.results(races: list, step: demoStep)
            source = "demo data"
            problem = nil
        } else if !base.isEmpty {
            source = live.sources.map { $0 == "nyt" ? "AP via NYT" : "CNN" }.joined(separator: " + ")
            problem = live.errors.isEmpty ? nil : "Partial feed: \(live.errors.count) file(s) failed"
        } else if let snap = await Feeds.siteFile("results-auto.json", as: ResultsFile.self), let r = snap.races {
            base = r
            source = "saved snapshot"
            problem = "Live feed unreachable; showing the site's saved copy"
        } else {
            problem = "Live feed unreachable (\(live.errors.first ?? "no data")); retrying"
        }
        if !base.isEmpty || results.isEmpty {
            // Calls count once 2 of the 4 news outlets agree (calls.json); demo data keeps its own calls.
            let confirmedBase = demo ? base : applyConsensus(base, calls: outletCalls)
            results = mergeResults(feed: confirmedBase, manual: manual?.races ?? [:])
            lastUpdate = Date()
            noteNewCalls()
        }
        nextUpdate = nextRefresh(after: Date())
        loading = false
    }

    private func loadSite() async {
        async let r = Feeds.siteFile("races.json", as: [Race].self)
        async let s = Feeds.siteFile("summary.json", as: SiteSummary.self)
        async let sc = Feeds.siteFile("schedule.json", as: Schedule.self)
        let (racesList, sum, sched) = await (r, s, sc)
        if let racesList {
            races = Dictionary(uniqueKeysWithValues: racesList.filter { $0.chamber != "governor" }.map { ($0.raceId, $0) })
            siteLoadedAt = Date()
        } else if races.isEmpty {
            problem = "Can't reach the forecast site; retrying"
        }
        if let sum { summary = sum }
        if let sched {
            let iso = ISO8601DateFormatter()
            var t: [String: Date] = [:]
            for g in sched.groups { if let d = iso.date(from: g.closeUtc) { for it in g.races { t[it.raceId] = d } } }
            closeTimes = t
        }
    }

    /// When to refresh next (demo data steps every minute so it visibly moves).
    private func nextRefresh(after now: Date) -> Date {
        now.addingTimeInterval(demo ? 60 : Self.interval)
    }

    // MARK: Derived views

    func pollsClosed(_ id: String, at now: Date = .now) -> Bool {
        guard let t = closeTimes[id] else { return true }
        return now >= t
    }

    struct Tally {
        var dWon = 0, rWon = 0, oWon = 0, dLead = 0, rLead = 0, open = 0, called = 0, up = 0
        var total = 0, needed = 0, model: Double?
        var flips: [(race: Race, from: String, to: String)] = []
        var controller: Side? { dWon >= needed ? .dem : rWon >= needed ? .rep : nil }
        var uncalled: Int { up - called }
        var dNeed: Int { max(0, needed - dWon) }
        var rNeed: Int { max(0, needed - rWon) }
    }

    func isFlip(_ id: String) -> Bool {
        guard let e = results[id], e.isCalled, let w = e.winnerSide, let r = races[id], let held = r.heldBy else { return false }
        return r.party(w) != held
    }

    // MARK: Called-race alerts

    /// One alert card: a single race, or several called at once.
    struct CallAlert: Identifiable, Equatable {
        let id = UUID()
        let raceIds: [String]
    }

    private(set) var alert: CallAlert?
    private var alertQueue: [CallAlert] = []
    private var knownCalled: Set<String>?
    private var alertTask: Task<Void, Never>?

    /// Queue alerts for races called since the last refresh: Senate races, competitive House races and
    /// flips get a card each (up to four per refresh); the rest share one summary card.
    private func noteNewCalls() {
        let now = Set(results.compactMap { id, e in e.isCalled && races[id] != nil ? id : nil })
        defer { knownCalled = now }
        guard let before = knownCalled else { return }  // first load: what's already called is old news
        let fresh = now.subtracting(before)
        guard !fresh.isEmpty else { return }
        let rank: (String) -> Int = { id in
            guard let r = self.races[id] else { return 9 }
            return self.isFlip(id) ? 0 : r.chamber == "senate" ? 1 : r.isCompetitive ? 2 : 3
        }
        let ordered = fresh.sorted { (rank($0), $0) < (rank($1), $1) }
        let headline = ordered.filter { rank($0) < 3 }.prefix(4)
        for id in headline { alertQueue.append(CallAlert(raceIds: [id])) }
        let rest = ordered.filter { !headline.contains($0) }
        if !rest.isEmpty { alertQueue.append(CallAlert(raceIds: rest)) }
        if alertQueue.count > 6 {  // fell behind: fold the backlog into one summary
            let ids = alertQueue.flatMap(\.raceIds)
            alertQueue = [CallAlert(raceIds: ids)]
        }
        runAlerts()
    }

    private func runAlerts() {
        guard alertTask == nil else { return }
        alertTask = Task { @MainActor [weak self] in
            while true {
                guard let self, !self.alertQueue.isEmpty else { break }
                let next = self.alertQueue.removeFirst()
                self.alert = next
                try? await Task.sleep(for: .seconds(next.raceIds.count > 1 ? 9 : 7))
                self.alert = nil
                try? await Task.sleep(for: .milliseconds(900))
            }
            self?.alertTask = nil
        }
    }

    func tally(_ chamber: String) -> Tally {
        let info = summary?.chambers[chamber]
        var t = Tally()
        t.dWon = info?.notUp["D"] ?? 0
        t.rWon = info?.notUp["R"] ?? 0
        t.total = info?.total ?? (chamber == "house" ? 435 : 100)
        t.needed = info?.needed ?? (chamber == "house" ? 218 : 51)
        t.model = info?.demSeats?.mean
        for race in races.values where race.chamber == chamber {
            t.up += 1
            let e = results[race.raceId]
            if let e, e.isCalled, let w = e.winnerSide {
                t.called += 1
                switch w { case .dem: t.dWon += 1; case .rep: t.rWon += 1; case .other: t.oWon += 1 }
                let to = race.party(w)
                if let from = race.heldBy, from != to { t.flips.append((race, from, to)) }
            } else if let sh = e?.shares {
                if sh.margin > 0 { t.dLead += 1 } else if sh.margin < 0 { t.rLead += 1 } else { t.open += 1 }
            } else {
                t.open += 1
            }
        }
        t.flips.sort { $0.race.raceId < $1.race.raceId }
        return t
    }

    /// Uncalled races, Senate first, then the closest House seats; races with no votes yet go last.
    func stillCounting() -> [Race] {
        races.values.filter { !(results[$0.raceId]?.isCalled ?? false) }
            .sorted { a, b in
                if a.chamber != b.chamber { return a.chamber == "senate" }
                let ma = results[a.raceId]?.shares.map { abs($0.margin) } ?? 999
                let mb = results[b.raceId]?.shares.map { abs($0.margin) } ?? 999
                return ma < mb
            }
    }

    /// Called seats that changed party, Senate first.
    func flippedRaces() -> [Race] {
        races.values.filter { isFlip($0.raceId) }
            .sorted { ($0.chamber == "senate" ? 0 : 1, $0.raceId) < ($1.chamber == "senate" ? 0 : 1, $1.raceId) }
    }

    struct Score {
        var n = 0, hits = 0
        var brier: Double?
        var upsets: [Race] = []
    }

    /// How the final forecast did on the Senate and House races called so far (same scoring as the website).
    func score() -> Score {
        var sc = Score()
        var sq = 0.0
        for r in races.values where r.uncontested != true {
            guard let p = r.pDem, let e = results[r.raceId], e.isCalled, let w = e.winnerSide, w != .other else { continue }
            let demWon = w == .dem
            sc.n += 1
            sq += (p - (demWon ? 1 : 0)) * (p - (demWon ? 1 : 0))
            if (p >= 0.5) == demWon { sc.hits += 1 } else { sc.upsets.append(r) }
        }
        sc.brier = sc.n > 0 ? sq / Double(sc.n) : nil
        sc.upsets.sort { abs(($0.pDem ?? 0.5) - 0.5) > abs(($1.pDem ?? 0.5) - 0.5) }
        return sc
    }
}

/// Plausible fake returns that fill in over successive refreshes, for checking the screen before polls close
/// (launch with -demo, or set the DemoMode default).
enum DemoData {
    static func results(races: [Race], step: Int) -> [String: ResultEntry] {
        var out: [String: ResultEntry] = [:]
        for r in races {
            var g = SplitMix(seed: UInt64(truncatingIfNeeded: r.raceId.hashValue))
            let start = Double(g.next() % 6)
            let reporting = min(100, max(0, (Double(step) - start) * Double(12 + g.next() % 14)))
            guard reporting > 0 else { out[r.raceId] = ResultEntry(status: "pending", reporting: 0, votes: Votes()); continue }
            let swing = Double(Int(g.next() % 1200) - 600) / 100
            let margin = (r.margin ?? 0) + swing
            let turnout = Double(150_000 + g.next() % 250_000) * (r.chamber == "senate" ? 12 : 1) * reporting / 100
            let other = turnout * 0.02
            let dem = (turnout - other) * (0.5 + margin / 200)
            let rep = turnout - other - dem
            let called = reporting >= 99 || (reporting > 40 && abs(margin) > 8) || (reporting > 75 && abs(margin) > 3)
            out[r.raceId] = ResultEntry(status: called ? "called" : "counting", reporting: reporting.rounded(),
                                        votes: Votes(dem: dem.rounded(), rep: rep.rounded(), other: other.rounded()),
                                        winner: called ? (margin > 0 ? "dem" : "rep") : nil)
        }
        return out
    }

    struct SplitMix {
        var state: UInt64
        init(seed: UInt64) { state = seed }
        mutating func next() -> UInt64 {
            state &+= 0x9E3779B97F4A7C15
            var z = state
            z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
            z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
            return z ^ (z >> 31)
        }
    }
}
