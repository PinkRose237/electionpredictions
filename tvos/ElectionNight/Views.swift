import SwiftUI

enum Theme {
    static let bg = Color(red: 0.055, green: 0.063, blue: 0.078)
    static let panel = Color(red: 0.094, green: 0.106, blue: 0.129)
    static let line = Color.white.opacity(0.10)
    static let ink = Color(white: 0.93)
    static let ink2 = Color(white: 0.70)
    static let ink3 = Color(white: 0.50)
    static let dem = Color(red: 0.29, green: 0.56, blue: 0.85)
    static let rep = Color(red: 0.89, green: 0.34, blue: 0.31)
    static let ind = Color(red: 0.85, green: 0.68, blue: 0.25)
    static let noRace = Color(red: 0.125, green: 0.135, blue: 0.155)
    static let pollsOpen = Color(red: 0.20, green: 0.215, blue: 0.245)
    static let awaiting = Color(red: 0.42, green: 0.44, blue: 0.49)

    static func party(_ p: String?) -> Color { p == "D" ? dem : p == "R" ? rep : ind }
    /// "Leading" shade: the party colour at partial strength, kept well clear of the greys.
    static func lean(_ c: Color) -> Color { c.opacity(0.55) }
}

/// Map / tile colour for one race: won (solid), leading (pale), counting with no votes, polls still open.
func raceFill(_ race: Race?, _ e: ResultEntry?, closed: Bool) -> Color {
    guard let race else { return Theme.noRace }
    if let e, e.isCalled, let w = e.winnerSide { return Theme.party(race.party(w)) }
    if let sh = e?.shares, sh.margin != 0 { return Theme.lean(Theme.party(race.party(sh.margin > 0 ? .dem : .rep))) }
    return closed ? Theme.awaiting : Theme.pollsOpen
}

// MARK: - Dashboard

struct DashboardView: View {
    @Environment(ResultsStore.self) private var store

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            if store.races.isEmpty {
                VStack(spacing: 24) {
                    ProgressView().scaleEffect(1.6)
                    Text(store.problem ?? "Loading races…").font(.system(size: 28)).foregroundStyle(Theme.ink2)
                }
            } else {
                // Five minutes before polls close, the countdown panel slides in on the right and the board
                // narrows to make room; it slides back out the moment they close.
                TimelineView(.periodic(from: .now, by: 1)) { ctx in
                    let up = store.nextClose(after: ctx.date)
                    let remaining = up.map { $0.at.timeIntervalSince(ctx.date) } ?? -1
                    let show = remaining > 0 && remaining <= PollClosePanel.lead
                    HStack(spacing: 0) {
                        VStack(spacing: 18) {
                            HeaderBar()
                            HStack(alignment: .top, spacing: 32) {
                                ChamberPanel(chamber: "senate")
                                ChamberPanel(chamber: "house")
                            }
                            KeyRacesStrip(perPage: show ? 3 : 4)
                        }
                        .padding(.horizontal, 56)
                        .padding(.vertical, 36)
                        if show, let up {
                            PollClosePanel(up: up, remaining: remaining)
                                .frame(width: PollClosePanel.width)
                                .transition(.move(edge: .trailing))
                        }
                    }
                    .animation(.spring(response: 0.8, dampingFraction: 0.86), value: show)
                }
                CallAlertView()
            }
        }
        .ignoresSafeArea()
        // Focusable so the Siri Remote's Play/Pause reaches us: it forces an immediate refresh.
        .focusable()
        .focusEffectDisabled()
        .onPlayPauseCommand { store.refreshNow() }
    }
}

// MARK: - Poll-closing countdown

/// The right-hand panel shown for the last five minutes before the next polls close.
struct PollClosePanel: View {
    static let lead: TimeInterval = 5 * 60
    static let width: CGFloat = 430
    let up: ResultsStore.UpcomingClose
    let remaining: TimeInterval

    private static let et: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        f.timeZone = TimeZone(identifier: "America/New_York")
        return f
    }()

    var body: some View {
        let secs = Int(remaining.rounded(.up))
        let urgent = secs <= 60
        let accent = urgent ? Theme.ind : Theme.dem
        let races = [up.senate > 0 ? "\(up.senate) Senate" : nil, up.house > 0 ? "\(up.house) House" : nil]
            .compactMap { $0 }.joined(separator: " · ")
        VStack(alignment: .leading, spacing: 18) {
            Text("POLLS CLOSE IN").font(.system(size: 24, weight: .heavy)).tracking(2).foregroundStyle(Theme.ink2)
            Text(String(format: "%d:%02d", secs / 60, secs % 60))
                .font(.system(size: 128, weight: .bold).monospacedDigit())
                .foregroundStyle(urgent ? Theme.ind : Theme.ink)
                .contentTransition(.numericText(countsDown: true))
                .minimumScaleFactor(0.6)
                .lineLimit(1)
            // Drains over the five minutes.
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.line)
                    Capsule().fill(accent).frame(width: g.size.width * max(0, remaining) / Self.lead)
                }
            }
            .frame(height: 8)
            Rectangle().fill(Theme.line).frame(height: 2).padding(.vertical, 6)
            Text("\(Self.et.string(from: up.at)) ET").font(.system(size: 40, weight: .bold)).foregroundStyle(Theme.ink)
            if !races.isEmpty {
                Text("\(races) race\(up.senate + up.house == 1 ? "" : "s")").font(.system(size: 24)).foregroundStyle(Theme.ink3)
            }
            VStack(alignment: .leading, spacing: 10) {
                ForEach(up.states, id: \.self) { st in
                    Text(st).font(.system(size: 30, weight: .semibold)).foregroundStyle(Theme.ink2).lineLimit(1)
                }
            }
            .padding(.top, 6)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 40)
        .padding(.top, 56)
        .padding(.bottom, 40)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.panel)
        .overlay(alignment: .leading) { Rectangle().fill(accent).frame(width: 6) }
        .animation(.easeInOut(duration: 0.4), value: urgent)
    }
}

// MARK: - Called-race alert

/// Slides down from the top when races are called: one card per notable race, or a summary card.
struct CallAlertView: View {
    @Environment(ResultsStore.self) private var store

    var body: some View {
        ZStack(alignment: .top) {
            if let a = store.alert {
                Group {
                    if a.raceIds.count == 1, let race = store.races[a.raceIds[0]] { single(race) } else { batch(a.raceIds) }
                }
                .padding(.top, 22)
                .transition(.move(edge: .top).combined(with: .opacity))
                .id(a.id)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(.spring(response: 0.6, dampingFraction: 0.84), value: store.alert?.id)
        .allowsHitTesting(false)
    }

    private func single(_ race: Race) -> some View {
        let e = store.results[race.raceId]
        let side = e?.winnerSide ?? .other
        let party = race.party(side)
        let color = Theme.party(party)
        let name = race.candidate(side)?.name ?? "Another candidate"
        let flip = store.isFlip(race.raceId)
        var detail: [String] = []
        if let sh = e?.shares { detail.append(String(format: "%.1f%% – %.1f%%", max(sh.dem, sh.rep), min(sh.dem, sh.rep))) }
        if let r = e?.reporting, r > 0 { detail.append("\(Int(r.rounded()))% in") }
        if let n = e?.confirmed { detail.append("Confirmed by \(n) of \(e?.outlets ?? 4) outlets") }
        if let l = race.label { detail.append("Rated \(l)") }
        return VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 14) {
                    Text("RACE CALL").font(.system(size: 20, weight: .heavy)).tracking(2).foregroundStyle(Theme.ink3)
                    if flip, let held = race.heldBy {
                        Text("FLIP \(held) → \(party)").font(.system(size: 18, weight: .heavy)).tracking(1)
                            .padding(.horizontal, 10).padding(.vertical, 3).background(Theme.ind, in: Capsule()).foregroundStyle(.black)
                    }
                }
                Text(displayName(race)).font(.system(size: 30, weight: .semibold)).foregroundStyle(Theme.ink2)
                Text("\(name) (\(party)) wins").font(.system(size: 46, weight: .bold)).foregroundStyle(color).lineLimit(1)
                if !detail.isEmpty { Text(detail.joined(separator: " · ")).font(.system(size: 22).monospacedDigit()).foregroundStyle(Theme.ink3) }
        }
        .padding(.leading, 46).padding(.trailing, 40).padding(.vertical, 22)
        .frame(minWidth: 760, alignment: .leading)
        .background(Theme.panel)
        .overlay(alignment: .leading) { Rectangle().fill(color).frame(width: 12) }
        .clipShape(RoundedRectangle(cornerRadius: 22))
        .fixedSize()
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(flip ? Theme.ind : color, lineWidth: 3))
        .shadow(color: .black.opacity(0.6), radius: 28, y: 12)
    }

    private func batch(_ ids: [String]) -> some View {
        let list = ids.compactMap { store.races[$0] }
        let d = list.filter { store.results[$0.raceId]?.winnerSide == .dem }.count
        let r = list.filter { store.results[$0.raceId]?.winnerSide == .rep }.count
        let shown = list.prefix(12)
        return VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 18) {
                Text("\(list.count) RACES CALLED").font(.system(size: 22, weight: .heavy)).tracking(2).foregroundStyle(Theme.ink2)
                Text("D \(d)").font(.system(size: 26, weight: .bold)).foregroundStyle(Theme.dem)
                Text("R \(r)").font(.system(size: 26, weight: .bold)).foregroundStyle(Theme.rep)
            }
            HStack(spacing: 10) {
                ForEach(shown, id: \.raceId) { race in
                    let side = store.results[race.raceId]?.winnerSide ?? .other
                    Text(race.short).font(.system(size: 20, weight: .bold)).lineLimit(1).fixedSize().padding(.horizontal, 10).padding(.vertical, 5)
                        .background(Theme.party(race.party(side)), in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(.white)
                }
                if list.count > shown.count { Text("+\(list.count - shown.count) more").font(.system(size: 20)).foregroundStyle(Theme.ink3) }
            }
        }
        .padding(.horizontal, 34).padding(.vertical, 22)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(Theme.line, lineWidth: 2))
        .fixedSize()
        .shadow(color: .black.opacity(0.6), radius: 28, y: 12)
    }
}

// MARK: - Header

struct HeaderBar: View {
    @Environment(ResultsStore.self) private var store
    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "h:mm:ss a"
        f.timeZone = TimeZone(identifier: "America/New_York")
        return f
    }()

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            HStack(alignment: .center, spacing: 24) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Election Night 2026").font(.system(size: 40, weight: .bold)).foregroundStyle(Theme.ink)
                    Text("Senate & House · live results").font(.system(size: 22)).foregroundStyle(Theme.ink3)
                }
                Spacer()
                status(now: ctx.date)
                Spacer()
                Text("\(Self.clock.string(from: ctx.date)) ET")
                    .font(.system(size: 36, weight: .semibold).monospacedDigit()).foregroundStyle(Theme.ink)
            }
        }
    }

    @ViewBuilder private func status(now: Date) -> some View {
        let ok = store.problem == nil && store.lastUpdate != nil
        HStack(spacing: 12) {
            Circle().fill(ok ? Color.green : Color.orange).frame(width: 14, height: 14)
            VStack(alignment: .leading, spacing: 2) {
                Text(store.source.map { "Live · \($0)" } ?? "Connecting…")
                    .font(.system(size: 22, weight: .semibold)).foregroundStyle(Theme.ink)
                Text(detail(now: now)).font(.system(size: 19).monospacedDigit())
                    .foregroundStyle(store.problem == nil ? Theme.ink3 : Color.orange)
            }
        }
    }

    private func detail(now: Date) -> String {
        if let p = store.problem { return p }
        guard let last = store.lastUpdate else { return "" }
        let ago = Int(now.timeIntervalSince(last))
        let next = store.nextUpdate.map { max(0, Int($0.timeIntervalSince(now))) }
        return "updated \(ago < 60 ? "\(ago)s" : "\(ago / 60)m") ago" + (next.map { " · next in \($0 / 60):\(String(format: "%02d", $0 % 60))" } ?? "")
    }
}

// MARK: - Chamber panel: scoreboard + map

struct ChamberPanel: View {
    @Environment(ResultsStore.self) private var store
    let chamber: String

    var body: some View {
        let t = store.tally(chamber)
        VStack(alignment: .leading, spacing: 14) {
            Scoreboard(title: chamber == "senate" ? "Senate" : "House", t: t)
            Group {
                if chamber == "senate" { SenateMap() } else { HouseMap() }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer(t)
        }
        .padding(22)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 18))
    }

    private func footer(_ t: ResultsStore.Tally) -> some View {
        var parts = ["\(t.called) of \(t.up) called"]
        if t.total != t.up { parts.append("\(t.total - t.up) not up") }
        if let m = t.model { parts.append("Model: D \(Int(m.rounded()))") }
        let flips = t.flips.prefix(6).map { "\($0.race.short) \($0.from)→\($0.to)" }.joined(separator: ", ")
        return VStack(alignment: .leading, spacing: 4) {
            Text(parts.joined(separator: " · ")).font(.system(size: 20)).foregroundStyle(Theme.ink3)
            if t.controller == nil && t.called > 0 {
                (Text("To win: ").foregroundStyle(Theme.ink3)
                 + Text("D need \(t.dNeed)").foregroundStyle(Theme.dem).bold()
                 + Text(" · ").foregroundStyle(Theme.ink3)
                 + Text("R need \(t.rNeed)").foregroundStyle(Theme.rep).bold()
                 + Text(" of \(t.uncalled) uncalled").foregroundStyle(Theme.ink3))
                    .font(.system(size: 20)).lineLimit(1)
            }
            if !t.flips.isEmpty {
                Text("\(t.flips.count) flip\(t.flips.count == 1 ? "" : "s"): \(flips)\(t.flips.count > 6 ? " +\(t.flips.count - 6) more" : "")")
                    .font(.system(size: 20, weight: .medium)).foregroundStyle(Theme.ink2).lineLimit(1)
            }
        }
    }
}

struct Scoreboard: View {
    let title: String
    let t: ResultsStore.Tally

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(title.uppercased()).font(.system(size: 26, weight: .heavy)).tracking(1.5).foregroundStyle(Theme.ink)
                Spacer()
                Text(t.controller.map { $0 == .dem ? "Democrats win control" : "Republicans win control" } ?? "\(t.needed) for control")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(t.controller.map { $0 == .dem ? Theme.dem : Theme.rep } ?? Theme.ink3)
            }
            HStack(alignment: .lastTextBaseline) {
                side(n: t.dWon, lead: t.dLead, label: "Democrats", color: Theme.dem, leading: true)
                Spacer()
                side(n: t.rWon, lead: t.rLead, label: "Republicans", color: Theme.rep, leading: false)
            }
            bar
        }
    }

    private func side(n: Int, lead: Int, label: String, color: Color, leading: Bool) -> some View {
        let num = Text("\(n)").font(.system(size: 64, weight: .bold).monospacedDigit()).foregroundStyle(color)
        let lbl = VStack(alignment: leading ? .leading : .trailing, spacing: 0) {
            Text(label).font(.system(size: 22, weight: .semibold)).foregroundStyle(Theme.ink2)
            Text(lead > 0 ? "+\(lead) leading" : " ").font(.system(size: 20)).foregroundStyle(Theme.ink3)
        }
        return HStack(alignment: .lastTextBaseline, spacing: 12) {
            if leading { num; lbl } else { lbl; num }
        }
    }

    private var bar: some View {
        GeometryReader { geo in
            let w = geo.size.width, total = Double(max(t.total, 1))
            let segs: [(Int, Color)] = [(t.dWon, Theme.dem), (t.dLead, Theme.lean(Theme.dem)),
                                        (t.open + t.oWon, Theme.pollsOpen),
                                        (t.rLead, Theme.lean(Theme.rep)), (t.rWon, Theme.rep)]
            ZStack(alignment: .topLeading) {
                HStack(spacing: 0) {
                    ForEach(Array(segs.enumerated()), id: \.offset) { _, s in
                        Rectangle().fill(s.1).frame(width: w * Double(s.0) / total)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 6))
                Rectangle().fill(Theme.ink).frame(width: 3, height: 34)
                    .offset(x: w * Double(t.needed) / total - 1.5, y: -5)
            }
        }
        .frame(height: 24)
        .animation(.easeInOut(duration: 0.6), value: t.dWon + t.rWon * 1000 + t.dLead * 1_000_000)
    }
}

// MARK: - Maps

struct SenateMap: View {
    @Environment(ResultsStore.self) private var store
    private let map = MapData.shared
    /// Small north-eastern states drawn as labelled boxes off the coast.
    private static let callouts = ["VT", "NH", "MA", "RI", "CT", "NJ", "DE", "MD"]
    /// Label offsets (points) where neighbouring labels would collide.
    private static let nudges: [String: CGPoint] = ["WV": CGPoint(x: -4, y: 6), "VA": CGPoint(x: 8, y: 2), "KY": CGPoint(x: 6, y: 2), "LA": CGPoint(x: -6, y: -4)]

    var body: some View {
        let byState = Dictionary(store.races.values.filter { $0.chamber == "senate" }.map { ($0.state, $0) }, uniquingKeysWith: { a, _ in a })
        let fills = byState.mapValues { raceFill($0, store.results[$0.raceId], closed: store.pollsClosed($0.raceId)) }
        Canvas { ctx, size in
            let reserve = 70.0
            let s = min((size.width - reserve) / map.width, size.height / map.height)
            let ox = (size.width - reserve - map.width * s) / 2, oy = (size.height - map.height * s) / 2
            let xf = CGAffineTransform(translationX: ox, y: oy).scaledBy(x: s, y: s)
            for (st, path) in map.statePaths {
                let p = path.applying(xf)
                ctx.fill(p, with: .color(fills[st] ?? Theme.noRace))
                ctx.stroke(p, with: .color(Theme.panel), lineWidth: 1.2)
            }
            // Flipped seats get a gold outline, drawn last so neighbours don't cover it.
            for (st, race) in byState where store.isFlip(race.raceId) {
                if let path = map.statePaths[st] { ctx.stroke(path.applying(xf), with: .color(Theme.ind), lineWidth: 4) }
            }
            for (st, c) in map.centers where byState[st] != nil && !Self.callouts.contains(st) {
                let nudge = Self.nudges[st] ?? .zero
                let pt = CGPoint(x: ox + c[0] * s + nudge.x, y: oy + c[1] * s + nudge.y)
                ctx.draw(Text(st).font(.system(size: 16, weight: .bold)).foregroundStyle(.white), at: pt)
            }
            // Callout boxes for the small states that hold Senate races, stacked in the Atlantic.
            let boxes = Self.callouts.filter { byState[$0] != nil }
            let side = 30.0, gap = 8.0
            let x = ox + map.width * s + 22
            var y = oy + (map.centers["VT"]?[1] ?? 120) * s - 20
            for st in boxes {
                let r = CGRect(x: x, y: y, width: side, height: side)
                ctx.fill(Path(roundedRect: r, cornerRadius: 4), with: .color(fills[st] ?? Theme.noRace))
                ctx.draw(Text(st).font(.system(size: 15, weight: .bold)).foregroundStyle(.white), at: CGPoint(x: r.midX, y: r.midY))
                if let c = map.centers[st] {
                    var l = Path()
                    l.move(to: CGPoint(x: ox + c[0] * s, y: oy + c[1] * s))
                    l.addLine(to: CGPoint(x: r.minX, y: r.midY))
                    ctx.stroke(l, with: .color(Theme.ink3.opacity(0.6)), lineWidth: 1)
                }
                y += side + gap
            }
        }
    }
}

struct HouseMap: View {
    @Environment(ResultsStore.self) private var store
    private let map = MapData.shared

    var body: some View {
        let h = map.house
        let fills = Dictionary(uniqueKeysWithValues: h.tiles.map { t in
            (t.id, raceFill(store.races[t.id], store.results[t.id], closed: store.pollsClosed(t.id)))
        })
        Canvas { ctx, size in
            let side = min(size.width / Double(h.cols), size.height / Double(h.rows))
            let ox = (size.width - side * Double(h.cols)) / 2, oy = (size.height - side * Double(h.rows)) / 2
            for t in h.tiles {
                let r = CGRect(x: ox + Double(t.x) * side, y: oy + Double(t.y) * side, width: side, height: side)
                ctx.fill(Path(roundedRect: r.insetBy(dx: 1.2, dy: 1.2), cornerRadius: side * 0.12), with: .color(fills[t.id] ?? Theme.noRace))
                var e = Path()
                if t.edges.contains("t") { e.move(to: CGPoint(x: r.minX, y: r.minY)); e.addLine(to: CGPoint(x: r.maxX, y: r.minY)) }
                if t.edges.contains("r") { e.move(to: CGPoint(x: r.maxX, y: r.minY)); e.addLine(to: CGPoint(x: r.maxX, y: r.maxY)) }
                if t.edges.contains("b") { e.move(to: CGPoint(x: r.minX, y: r.maxY)); e.addLine(to: CGPoint(x: r.maxX, y: r.maxY)) }
                if t.edges.contains("l") { e.move(to: CGPoint(x: r.minX, y: r.minY)); e.addLine(to: CGPoint(x: r.minX, y: r.maxY)) }
                ctx.stroke(e, with: .color(Theme.ink.opacity(0.85)), lineWidth: 2)
            }
            for t in h.tiles where store.isFlip(t.id) {
                let r = CGRect(x: ox + Double(t.x) * side, y: oy + Double(t.y) * side, width: side, height: side)
                ctx.stroke(Path(roundedRect: r.insetBy(dx: 2.5, dy: 2.5), cornerRadius: side * 0.12), with: .color(Theme.ind), lineWidth: 3)
            }
            for (st, c) in h.labels {
                let pt = CGPoint(x: ox + c[0] * side, y: oy + c[1] * side)
                ctx.draw(Text(st).font(.system(size: max(11, side * 0.52), weight: .heavy)).foregroundStyle(.white), at: pt)
            }
        }
    }
}

// MARK: - Key races strip

struct KeyRacesStrip: View {
    @Environment(ResultsStore.self) private var store
    /// Four cards across normally, three while the poll-closing panel narrows the board.
    var perPage = 4
    static let pageSeconds = 10.0

    var body: some View {
        let list = store.keyRaces()
        let pages = max(1, Int(ceil(Double(list.count) / Double(perPage))))
        TimelineView(.periodic(from: .now, by: Self.pageSeconds)) { ctx in
            let page = Int(ctx.date.timeIntervalSince1970 / Self.pageSeconds) % pages
            let slice = Array(list.dropFirst(page * perPage).prefix(perPage))
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("KEY RACES").font(.system(size: 22, weight: .heavy)).tracking(1.5).foregroundStyle(Theme.ink2)
                    Text("page \(page + 1) of \(pages)").font(.system(size: 19)).foregroundStyle(Theme.ink3)
                    Spacer()
                    Legend()
                }
                HStack(spacing: 20) {
                    ForEach(slice) { RaceCard(race: $0) }
                    ForEach(slice.count..<perPage, id: \.self) { _ in Color.clear.frame(maxWidth: .infinity) }
                }
                .id(page)
                .transition(.opacity)
            }
            .animation(.easeInOut(duration: 0.5), value: page)
        }
        .frame(height: 236)
    }
}

struct Legend: View {
    var body: some View {
        HStack(spacing: 18) {
            item(Theme.dem, "Won D"); item(Theme.lean(Theme.dem), "Leading D")
            item(Theme.lean(Theme.rep), "Leading R"); item(Theme.rep, "Won R")
            item(Theme.awaiting, "Polls closed"); item(Theme.pollsOpen, "Polls open")
            HStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 3).stroke(Theme.ind, lineWidth: 3).frame(width: 16, height: 16)
                Text("Flip").font(.system(size: 18)).foregroundStyle(Theme.ink3)
            }
        }
    }
    private func item(_ c: Color, _ s: String) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 3).fill(c).frame(width: 18, height: 18)
            Text(s).font(.system(size: 18)).foregroundStyle(Theme.ink3)
        }
    }
}

struct RaceCard: View {
    @Environment(ResultsStore.self) private var store
    let race: Race

    var body: some View {
        let e = store.results[race.raceId]
        let sh = e?.shares
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text(race.short).font(.system(size: 26, weight: .bold)).foregroundStyle(Theme.ink).fixedSize()
                if let l = race.label {
                    Text(l).font(.system(size: 16, weight: .semibold)).padding(.horizontal, 8).padding(.vertical, 2)
                        .background(Theme.line, in: Capsule()).foregroundStyle(Theme.ink2).fixedSize()
                }
                Spacer(minLength: 6)
                badge(e).lineLimit(1).minimumScaleFactor(0.75)
            }
            row(.dem, e, sh?.dem)
            row(.rep, e, sh?.rep)
            Text(foot(e, sh)).font(.system(size: 17).monospacedDigit()).foregroundStyle(Theme.ink3).lineLimit(1)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 14))
        .overlay(alignment: .leading) {
            if let e, e.isCalled, let w = e.winnerSide {
                UnevenRoundedRectangle(topLeadingRadius: 14, bottomLeadingRadius: 14).fill(Theme.party(race.party(w))).frame(width: 6)
            }
        }
    }

    @ViewBuilder private func badge(_ e: ResultEntry?) -> some View {
        if let e, e.isCalled, let w = e.winnerSide {
            Text("✓ \(lastName(race.candidate(w)?.name) ?? "Called")")
                .font(.system(size: 18, weight: .bold)).foregroundStyle(Theme.party(race.party(w)))
        } else if !store.pollsClosed(race.raceId) {
            Text("Polls open").font(.system(size: 18)).foregroundStyle(Theme.ink3)
        } else if e?.status == "runoff" {
            Text("Runoff").font(.system(size: 18, weight: .semibold)).foregroundStyle(Theme.ind)
        } else {
            Text(e?.awaiting.map { "\($0) of \(e?.outlets ?? 4) called" } ?? (e?.shares == nil ? "Awaiting votes" : "Counting")).font(.system(size: 18)).foregroundStyle(Theme.ink3)
        }
    }

    @ViewBuilder private func row(_ side: Side, _ e: ResultEntry?, _ pct: Double?) -> some View {
        if let c = race.candidate(side) {
            let color = Theme.party(c.party)
            let won = e?.isCalled == true && e?.winnerSide == side
            VStack(spacing: 4) {
                HStack {
                    Text("\(c.name) (\(c.party ?? "?"))\(won ? " ✓" : "")")
                        .font(.system(size: 19, weight: won ? .bold : .regular)).foregroundStyle(Theme.ink).lineLimit(1)
                    Spacer()
                    Text(pct.map { String(format: "%.1f%%", $0) } ?? "—")
                        .font(.system(size: 21, weight: .semibold).monospacedDigit()).foregroundStyle(Theme.ink)
                }
                GeometryReader { g in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Theme.line)
                        Capsule().fill(color).frame(width: g.size.width * (pct ?? 0) / 100)
                    }
                }
                .frame(height: 6)
            }
        } else {
            Text(race.uncontested == true ? "Uncontested" : "—").font(.system(size: 19)).foregroundStyle(Theme.ink3)
        }
    }

    private func foot(_ e: ResultEntry?, _ sh: (dem: Double, rep: Double, other: Double, margin: Double, total: Double)?) -> String {
        var parts: [String] = []
        if let r = e?.reporting, sh != nil || r > 0 { parts.append("\(Int(r.rounded()))% in") }
        if let m = race.margin { parts.append("Model \(fmtMargin(m))") }
        if let sh { parts.append("Now \(fmtMargin(sh.margin))") }
        return parts.isEmpty ? " " : parts.joined(separator: " · ")
    }
}

/// "Georgia Senate" as the data has it; House seats spelled out ("Florida 14th District", "Alaska At-Large").
func displayName(_ race: Race) -> String {
    guard race.chamber == "house", let d = race.district else { return race.name }
    let state = race.stateName ?? race.state
    if d == 0 { return "\(state) At-Large" }
    let suffix = (11...13).contains(d % 100) ? "th" : ["th", "st", "nd", "rd"][min(d % 10, 4) < 4 ? d % 10 : 0]
    return "\(state) \(d)\(suffix) District"
}

func fmtMargin(_ m: Double) -> String {
    abs(m) < 0.05 ? "Even" : "\(m > 0 ? "D" : "R")+\(String(format: "%.1f", abs(m)))"
}

func lastName(_ name: String?) -> String? {
    name?.split(separator: " ").last.map(String.init)
}
