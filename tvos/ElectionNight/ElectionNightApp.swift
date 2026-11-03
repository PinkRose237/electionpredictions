import SwiftUI
import UIKit

@main
struct ElectionNightApp: App {
    @State private var store = ResultsStore()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            DashboardView()
                .environment(store)
                .preferredColorScheme(.dark)
                .onAppear {
                    // A wall display: never let the Apple TV dim or start the screen saver while this is open.
                    UIApplication.shared.isIdleTimerDisabled = true
                    store.start()
                }
                .onChange(of: phase) { _, p in
                    UIApplication.shared.isIdleTimerDisabled = p == .active
                    if p == .active { store.refreshNow() }
                }
        }
    }
}
