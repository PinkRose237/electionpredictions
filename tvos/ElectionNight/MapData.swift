import SwiftUI

/// Bundled map geometry (Resources/maps.json, built by tvos/tools/make_maps.py): state outlines in a
/// 1000-unit-wide Albers USA box, and a one-tile-per-seat House cartogram.
struct MapData: Decodable, Sendable {
    let width: Double
    let height: Double
    let states: [String: [[Double]]]   // rings as flat x,y lists
    let centers: [String: [Double]]
    let house: House

    struct House: Decodable, Sendable {
        let cols: Int
        let rows: Int
        let tiles: [Tile]
        let labels: [String: [Double]]
    }
    struct Tile: Decodable, Sendable {
        let id: String
        let st: String
        let x: Int
        let y: Int
        let edges: String   // which sides (t, r, b, l) face another state
    }

    static let shared: MapData = {
        guard let url = Bundle.main.url(forResource: "maps", withExtension: "json"),
              let d = try? Data(contentsOf: url), let m = try? JSONDecoder().decode(MapData.self, from: d) else {
            fatalError("maps.json missing from the app bundle")
        }
        return m
    }()

    /// One Path per state in map units (scale it with a transform when drawing).
    let statePaths: [String: Path]

    enum CodingKeys: String, CodingKey { case width, height, states, centers, house }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        width = try c.decode(Double.self, forKey: .width)
        height = try c.decode(Double.self, forKey: .height)
        states = try c.decode([String: [[Double]]].self, forKey: .states)
        centers = try c.decode([String: [Double]].self, forKey: .centers)
        house = try c.decode(House.self, forKey: .house)
        var paths: [String: Path] = [:]
        for (st, rings) in states {
            var p = Path()
            for r in rings where r.count >= 6 {
                p.move(to: CGPoint(x: r[0], y: r[1]))
                stride(from: 2, to: r.count - 1, by: 2).forEach { p.addLine(to: CGPoint(x: r[$0], y: r[$0 + 1])) }
                p.closeSubpath()
            }
            paths[st] = p
        }
        statePaths = paths
    }
}
