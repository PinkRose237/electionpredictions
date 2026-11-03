import Foundation

/// Live results feeds, the same ones the website pulls (site/live.js; keep the two in step).
/// Primary: The New York Times' results JSON (AP votes and calls; `eevp` = AP's estimated share of the
/// expected vote counted). Backup: CNN's national-races JSON, used only for races the primary lacks.
enum Feeds {
    static let site = URL(string: "https://pinkrose237.github.io/electionpredictions/data/")!
    static let nyt = ["senate", "house"].map { URL(string: "https://static01.nyt.com/elections-assets/pages/data/2026-11-03/results-\($0).json")! }
    static let cnn = ["SG", "HG"].map { URL(string: "https://politics.api.cnn.io/results/national-races/2026-\($0).json")! }

    static let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.timeoutIntervalForRequest = 30
        return URLSession(configuration: c)
    }()

    static func data(_ url: URL) async throws -> Data {
        let (d, resp) = try await session.data(from: url)
        if let h = resp as? HTTPURLResponse, !(200..<300).contains(h.statusCode) {
            throw URLError(.badServerResponse, userInfo: [NSLocalizedDescriptionKey: "HTTP \(h.statusCode) for \(url.lastPathComponent)"])
        }
        return d
    }

    static let snake: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()

    /// A site data file, cache-busted. nil when absent (results.json before anything is published).
    static func siteFile<T: Decodable>(_ name: String, as: T.Type) async -> T? {
        var c = URLComponents(url: site.appendingPathComponent(name), resolvingAgainstBaseURL: false)!
        c.queryItems = [URLQueryItem(name: "t", value: String(Int(Date().timeIntervalSince1970)))]
        guard let d = try? await data(c.url!) else { return nil }
        return try? snake.decode(T.self, from: d)
    }

    struct LiveResult: Sendable {
        var races: [String: ResultEntry] = [:]
        var by: [String: String] = [:]
        var sources: [String] = []
        var errors: [String] = []
    }

    static func fetchLive(races: [Race]) async -> LiveResult {
        let byId = Dictionary(uniqueKeysWithValues: races.map { ($0.raceId, $0) })
        let resolve = Resolver(ids: Set(byId.keys))
        var out = LiveResult()
        for (name, urls, parse) in [("nyt", nyt, parseNYT), ("cnn", cnn, parseCNN)] as [(String, [URL], (Data, [String: Race], Resolver) throws -> [String: ResultEntry])] {
            if out.races.count >= byId.count { break }
            var added = 0
            await withTaskGroup(of: (URL, Result<Data, Error>).self) { group in
                for u in urls { group.addTask { do { return (u, .success(try await data(u))) } catch { return (u, .failure(error)) } } }
                for await (u, res) in group {
                    switch res {
                    case .failure(let e): out.errors.append("\(name) \(u.lastPathComponent): \(e.localizedDescription)")
                    case .success(let d):
                        do {
                            for (id, e) in try parse(d, byId, resolve) where out.races[id] == nil {
                                out.races[id] = e; out.by[id] = name; added += 1
                            }
                        } catch { out.errors.append("\(name) \(u.lastPathComponent): \(error.localizedDescription)") }
                    }
                }
            }
            if added > 0 { out.sources.append(name) }
        }
        return out
    }

    // MARK: Race resolution

    struct Resolver: Sendable {
        let ids: Set<String>
        func callAsFunction(_ st: String?, _ chamber: String?, _ district: String?, special: Bool) -> String? {
            guard let st, let chamber else { return nil }
            switch chamber {
            case "senate":
                let order = special ? ["\(st)-SEN-SP", "\(st)-SEN"] : ["\(st)-SEN", "\(st)-SEN-SP"]
                return order.first(where: ids.contains)
            case "house":
                guard let d = district.flatMap({ Int($0) }) else { return nil }
                let id = String(format: "%@-%02d", st, d)
                if ids.contains(id) { return id }
                if d <= 1, ids.contains("\(st)-00") { return "\(st)-00" }
                return nil
            default: return nil
            }
        }
    }

    // MARK: Candidate -> side matching

    struct FeedCand { var key = ""; var first = ""; var last = ""; var party = ""; var votes = 0.0; var winner = false; var runoff = false }

    static func tokens(_ s: String?) -> [String] {
        let folded = (s ?? "").folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .init(identifier: "en_US"))
        let noParens = folded.replacingOccurrences(of: #"\(.*?\)"#, with: " ", options: .regularExpression)
        let letters = noParens.replacingOccurrences(of: #"[^a-z\s-]"#, with: " ", options: .regularExpression)
        return letters.split(whereSeparator: { $0 == " " || $0 == "-" || $0 == "\n" || $0 == "\t" }).map(String.init)
            .filter { !["jr", "sr", "ii", "iii", "iv"].contains($0) }
    }

    static func fit(_ ours: String?, _ c: FeedCand, _ side: Side) -> Double {
        let t = tokens(ours), last = tokens(c.last)
        var s = 0.0
        if !t.isEmpty, !last.isEmpty, last.allSatisfy(t.contains) {
            s += 2
            if let f = tokens(c.first).first, t.first == f { s += 1 }
        }
        if (side == .dem && c.party == "DEM") || (side == .rep && c.party == "REP") { s += 0.5 }
        return s
    }

    static func entry(race: Race, cands: [FeedCand], won: [Int], runoff: Bool, final: Bool, reporting: Double?, updatedAt: String?) -> ResultEntry {
        var pairs: [(Double, Double, Side, Int)] = []
        for (i, c) in cands.enumerated() {
            for side in [Side.dem, .rep] {
                let s = fit(race.candidate(side)?.name, c, side)
                if s >= 0.5 { pairs.append((s, c.votes, side, i)) }
            }
        }
        pairs.sort { $0.0 != $1.0 ? $0.0 > $1.0 : $0.1 > $1.1 }
        var pick: [Side: Int] = [:], used = Set<Int>()
        for (_, _, side, i) in pairs where pick[side] == nil && !used.contains(i) { pick[side] = i; used.insert(i) }
        var v = Votes(dem: nil, rep: nil, other: 0)
        for (i, c) in cands.enumerated() {
            if i == pick[.dem] { v.dem = c.votes } else if i == pick[.rep] { v.rep = c.votes } else { v.other! += c.votes }
        }
        let total = (v.dem ?? 0) + (v.rep ?? 0) + (v.other ?? 0)
        if total == 0 { v.other = nil }
        var winner: Side?
        if let w = won.first { winner = w == pick[.dem] ? .dem : w == pick[.rep] ? .rep : .other }
        let status = final && winner != nil ? "final" : winner != nil ? "called" : runoff ? "runoff"
            : (total > 0 || (reporting ?? 0) > 0) ? "counting" : "pending"
        return ResultEntry(status: status, reporting: reporting.map { ($0 * 10).rounded() / 10 }, votes: v,
                           winner: winner?.rawValue, updatedAt: updatedAt)
    }

    // MARK: NYT

    struct NYTFile: Decodable { let races: [NYTRace] }
    struct NYTRace: Decodable {
        let officeId: String?
        let seatNumber: String?
        let raceTypeId: String?
        let type: String?
        let certified: Bool?
        let outcome: Outcome?
        let candidateMetadata: [String: Meta]?
        let topReportingUnit: Unit?
        let updatedAt: String?
        struct Outcome: Decodable { let won: [FlexID]?; let advancedToRunoff: [FlexID]? }
        struct Meta: Decodable { let nytId: String?; let firstName: String?; let lastName: String?; let party: Party? }
        struct Party: Decodable { let nytId: String? }
        struct Unit: Decodable {
            let level: String?
            let statePostal: String?
            let eevp: Double?
            let providerUpdatedAt: String?
            let candidates: [Cand]?
        }
        struct Cand: Decodable { let nytId: String?; let votes: V? }
        struct V: Decodable { let total: Double? }
    }
    /// A candidate id given either as a string or as an object with an id; anything else decodes as empty.
    struct FlexID: Decodable {
        let id: String
        init(from decoder: Decoder) throws {
            if let s = try? decoder.singleValueContainer().decode(String.self) { id = s; return }
            struct O: Decodable { let nytId: String? }
            id = (try? O(from: decoder))?.nytId ?? ""
        }
    }

    static func parseNYT(_ d: Data, _ byId: [String: Race], _ resolve: Resolver) throws -> [String: ResultEntry] {
        let file = try snake.decode(NYTFile.self, from: d)
        let chamberOf = ["S": "senate", "H": "house", "G": "governor"]
        var out: [String: ResultEntry] = [:]
        for r in file.races {
            guard let ru = r.topReportingUnit, ru.level == "state" else { continue }
            let special = r.raceTypeId == "W" || (r.type ?? "").lowercased().contains("special")
            guard let id = resolve(ru.statePostal, chamberOf[r.officeId ?? ""], r.seatNumber, special: special),
                  out[id] == nil, let race = byId[id] else { continue }
            // Index by each entry's own id: the snake-case key strategy can rewrite dictionary keys.
            let meta = Dictionary((r.candidateMetadata ?? [:]).values.compactMap { m in m.nytId.map { ($0, m) } }, uniquingKeysWith: { a, _ in a })
            let cands = (ru.candidates ?? []).map { c -> FeedCand in
                let m = meta[c.nytId ?? ""]
                let p = m?.party?.nytId ?? ""
                return FeedCand(key: c.nytId ?? "", first: m?.firstName ?? "", last: m?.lastName ?? "",
                                party: p == "GOP" ? "REP" : p, votes: c.votes?.total ?? 0)
            }
            let won = (r.outcome?.won ?? []).compactMap { w in cands.firstIndex { $0.key == w.id } }
            out[id] = entry(race: race, cands: cands, won: won, runoff: !(r.outcome?.advancedToRunoff ?? []).isEmpty,
                            final: r.certified ?? false, reporting: ru.eevp, updatedAt: ru.providerUpdatedAt ?? r.updatedAt)
        }
        return out
    }

    // MARK: CNN

    struct CNNRace: Decodable {
        let contestType: String?
        let raceType: String?
        let ecKey: String?
        let stateAbbreviation: String?
        let percentReporting: Double?
        let extractedAt: String?
        let candidates: [Cand]?
        struct Cand: Decodable {
            let firstName: String?
            let lastName: String?
            let majorParty: String?
            let voteNum: Double?
            let winner: Bool?
            let runoffCandidate: Bool?
        }
    }

    static func parseCNN(_ d: Data, _ byId: [String: Race], _ resolve: Resolver) throws -> [String: ResultEntry] {
        let list = try JSONDecoder().decode([CNNRace].self, from: d)
        let chamberOf = ["S": "senate", "H": "house", "G": "governor"]
        var out: [String: ResultEntry] = [:]
        for r in list where r.contestType != "HQ" {  // unexpired-term specials; we track the full-term race
            let chamber = chamberOf[r.raceType ?? ""]
            let district = chamber == "house" ? r.ecKey?.split(separator: "-").last.map(String.init) : nil
            guard let id = resolve(r.stateAbbreviation, chamber, district, special: r.contestType == "SP"),
                  out[id] == nil, let race = byId[id] else { continue }
            let cands = (r.candidates ?? []).map {
                FeedCand(first: $0.firstName ?? "", last: $0.lastName ?? "", party: $0.majorParty ?? "",
                         votes: $0.voteNum ?? 0, winner: $0.winner ?? false, runoff: $0.runoffCandidate ?? false)
            }
            var at = r.extractedAt
            if let a = at, a.range(of: #"(Z|[+-]\d\d:?\d\d)$"#, options: .regularExpression) == nil { at = a + "Z" }
            out[id] = entry(race: race, cands: cands, won: cands.indices.filter { cands[$0].winner },
                            runoff: cands.contains { $0.runoff }, final: false, reporting: r.percentReporting, updatedAt: at)
        }
        return out
    }
}
