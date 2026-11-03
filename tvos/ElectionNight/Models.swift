import Foundation

// MARK: - Site data (https://pinkrose237.github.io/electionpredictions/data/, see docs/DATA_CONTRACT.md)

struct Candidate: Decodable, Hashable, Sendable {
    let name: String
    let party: String?
}

struct Race: Decodable, Identifiable, Sendable {
    let raceId: String
    let chamber: String
    let state: String
    let stateName: String?
    let district: Int?
    let name: String
    let short: String
    let dem: Candidate?
    let rep: Candidate?
    let label: String?
    let margin: Double?
    let pDem: Double?
    let holderParty: String?
    let incumbentParty: String?
    let uncontested: Bool?

    var id: String { raceId }
    var heldBy: String? { holderParty ?? incumbentParty }
    func candidate(_ side: Side) -> Candidate? { side == .dem ? dem : side == .rep ? rep : nil }
    /// Party letter of whoever stands on a side ("I" for Osborn on Nebraska's D side).
    func party(_ side: Side) -> String { candidate(side)?.party ?? (side == .dem ? "D" : side == .rep ? "R" : "O") }
    var isCompetitive: Bool {
        guard let l = label else { return false }
        if l.hasPrefix("Lean") || l == "Tossup" { return true }
        return chamber == "senate" && l.hasPrefix("Likely")
    }
}

struct SiteSummary: Decodable, Sendable {
    let chambers: [String: ChamberInfo]
}

struct ChamberInfo: Decodable, Sendable {
    let total: Int
    let needed: Int
    let notUp: [String: Int]
    let demSeats: SeatDist?
    let repSeats: SeatDist?
    struct SeatDist: Decodable, Sendable { let mean: Double }
}

struct Schedule: Decodable, Sendable {
    let groups: [Group]
    struct Group: Decodable, Sendable {
        let closeUtc: String
        let races: [Item]
    }
    struct Item: Decodable, Sendable { let raceId: String }
}

// MARK: - Results (results.json overrides, results-auto.json snapshot, live feeds)

enum Side: String, Sendable { case dem, rep, other }

struct Votes: Codable, Sendable, Equatable {
    var dem: Double?
    var rep: Double?
    var other: Double?
}

struct ResultEntry: Codable, Sendable {
    var status: String?
    var reporting: Double?
    var votes: Votes?
    var winner: String?
    var updatedAt: String?
    var note: String?

    var winnerSide: Side? { winner.flatMap(Side.init(rawValue:)) }
    var isCalled: Bool { (status == "called" || status == "final") && winner != nil }

    /// Two-party-plus-other shares in percent and the D-minus-R margin, once votes exist.
    var shares: (dem: Double, rep: Double, other: Double, margin: Double, total: Double)? {
        guard let v = votes else { return nil }
        let d = v.dem ?? 0, r = v.rep ?? 0, o = v.other ?? 0, t = d + r + o
        guard t > 0 else { return nil }
        return (100 * d / t, 100 * r / t, 100 * o / t, 100 * (d - r) / t, t)
    }

    /// True when the admin entry changes anything (a pending status and empty fields mean "use the feed").
    var isOverride: Bool {
        (status != nil && status != "pending") || reporting != nil
            || votes?.dem != nil || votes?.rep != nil || votes?.other != nil || !(note ?? "").isEmpty
    }
}

struct ResultsFile: Decodable, Sendable {
    let updatedAt: String?
    let races: [String: ResultEntry]?
    let by: [String: String]?
}

/// Lay the admin's manual entries over feed entries, field by field (same rules as site/live.js mergeResults).
func mergeResults(feed: [String: ResultEntry], manual: [String: ResultEntry]) -> [String: ResultEntry] {
    var out = feed
    for (id, m) in manual where m.isOverride {
        var e = out[id] ?? ResultEntry(status: "pending", reporting: nil, votes: Votes(), winner: nil)
        if let s = m.status, s != "pending" { e.status = s; e.winner = m.winner }
        if let r = m.reporting { e.reporting = r }
        var v = e.votes ?? Votes()
        if let x = m.votes?.dem { v.dem = x }
        if let x = m.votes?.rep { v.rep = x }
        if let x = m.votes?.other { v.other = x }
        e.votes = v
        if let n = m.note, !n.isEmpty { e.note = n }
        out[id] = e
    }
    return out
}
