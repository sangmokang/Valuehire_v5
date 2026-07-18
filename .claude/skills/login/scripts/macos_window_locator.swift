import CoreGraphics
import Darwin
import Foundation

private struct Options {
    let pid: Int
    let marker: String
    let left: Double
    let top: Double
    let width: Double
    let height: Double
    let tolerance: Double
}

private func fail(_ message: String, code: Int32 = 2) -> Never {
    if let data = (message + "\n").data(using: .utf8) {
        FileHandle.standardError.write(data)
    }
    exit(code)
}

private func parseOptions() -> Options {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard arguments.count.isMultiple(of: 2) else {
        fail("window locator requires flag/value pairs")
    }
    var values: [String: String] = [:]
    var index = 0
    while index < arguments.count {
        let flag = arguments[index]
        guard flag.hasPrefix("--"), index + 1 < arguments.count else {
            fail("invalid window locator argument")
        }
        guard values[flag] == nil else {
            fail("duplicate window locator argument")
        }
        values[flag] = arguments[index + 1]
        index += 2
    }
    let expected = Set(["--pid", "--marker", "--left", "--top", "--width", "--height", "--tolerance"])
    guard Set(values.keys) == expected,
          let pidText = values["--pid"], let pid = Int(pidText), pid > 0,
          let marker = values["--marker"],
          let leftText = values["--left"], let left = Double(leftText), left.isFinite,
          let topText = values["--top"], let top = Double(topText), top.isFinite,
          let widthText = values["--width"], let width = Double(widthText), width.isFinite, width > 0,
          let heightText = values["--height"], let height = Double(heightText), height.isFinite, height > 0,
          let toleranceText = values["--tolerance"], let tolerance = Double(toleranceText),
          tolerance.isFinite, tolerance >= 0 else {
        fail("invalid window locator values")
    }
    return Options(
        pid: pid,
        marker: marker,
        left: left,
        top: top,
        width: width,
        height: height,
        tolerance: tolerance
    )
}

private func number(_ dictionary: [String: Any], _ key: String) -> Double? {
    (dictionary[key] as? NSNumber)?.doubleValue
}

private func near(_ actual: Double, _ expected: Double, tolerance: Double) -> Bool {
    abs(actual - expected) <= tolerance
}

private let options = parseOptions()
guard let rawWindows = CGWindowListCopyWindowInfo(
    [.optionAll, .excludeDesktopElements],
    kCGNullWindowID
) as? [[String: Any]] else {
    fail("CoreGraphics window enumeration unavailable", code: 1)
}

var matches: [[String: Any]] = []
for window in rawWindows {
    // Filter ownership before reading or serializing the window title.  The
    // output therefore cannot disclose titles owned by unrelated processes.
    guard let ownerPID = (window[kCGWindowOwnerPID as String] as? NSNumber)?.intValue,
          ownerPID == options.pid,
          let layer = (window[kCGWindowLayer as String] as? NSNumber)?.intValue,
          layer == 0,
          let onScreen = (window[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue,
          onScreen,
          let bounds = window[kCGWindowBounds as String] as? [String: Any],
          let left = number(bounds, "X"),
          let top = number(bounds, "Y"),
          let width = number(bounds, "Width"),
          let height = number(bounds, "Height"),
          near(left, options.left, tolerance: options.tolerance),
          near(top, options.top, tolerance: options.tolerance),
          near(width, options.width, tolerance: options.tolerance),
          near(height, options.height, tolerance: options.tolerance),
          let windowID = (window[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
          windowID > 0 else {
        continue
    }
    // The first, pre-focus pass intentionally uses an empty marker and must not
    // read or serialize the owner's current tab title.  After the exact bounds
    // identify one window, the second pass requires the injected marker.
    var title = ""
    if !options.marker.isEmpty {
        guard let candidateTitle = window[kCGWindowName as String] as? String,
              candidateTitle.hasPrefix(options.marker) else {
            continue
        }
        title = candidateTitle
    }
    matches.append([
        "cg_window_id": Int(windowID),
        "owner_pid": ownerPID,
        "layer": layer,
        "title": title,
        "bounds": [
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        ],
        "on_screen": true,
    ])
}

guard JSONSerialization.isValidJSONObject(matches),
      let output = try? JSONSerialization.data(withJSONObject: matches, options: []) else {
    fail("could not encode CoreGraphics result", code: 1)
}
FileHandle.standardOutput.write(output)
