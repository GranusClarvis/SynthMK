# SynthMK

Checkmk synthetic monitoring addon for browser-recorded website flows.

SynthMK's first target is deliberately small:

1. Record or define a readable browser flow.
2. Run it with a Chrome/Playwright-based runner.
3. Emit Checkmk-compatible service output.
4. Show the result as a normal Checkmk service.

The product direction is simplicity first. Users should not need to write
Playwright or Selenium code for common checks.

## MVP Components

- `flows/` - readable flow examples.
- `runner/` - synthetic runner that executes flows and returns Checkmk output.
- `checkmk/` - Checkmk local-check/addon skeleton.
- `extension/` - Chrome recorder MVP.
- `docs/` - architecture, GOAT reference audit, product roadmap, examples.

## Reference

GOAT is a reference point, not the final architecture. Useful concepts include
its Chrome recorder event capture, selector generation, recorded step model, and
Playwright runner behavior. SynthMK keeps the Checkmk user flow as the center of
gravity.

