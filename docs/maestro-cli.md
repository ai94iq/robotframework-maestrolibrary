# Maestro CLI coverage

The library talks to `maestro mcp`. What the other `maestro` subcommands do, and where it lives here:

| `maestro` | Here |
|---|---|
| `test` (flows, tags, `-e`) | `Run Flow` |
| `print-hierarchy`, `query` | `Get Source`, `Get Text`, `Get Element Attribute`, the Should keywords |
| `list-devices` | the `device` import argument; the first connected device by default |
| `record` | `Start/Stop Screen Recording` |
| `check-syntax` | `Run Flow` fails with Maestro's parse error and its line |
| `start-device` | not a test step: boot the emulator before the run, e.g. `maestro start-device --platform android` in CI |
| `studio`, `chat`, `driver`, `cloud`, `login`, ... | interactive or Maestro Cloud tools, not used |

Flow commands without a keyword, still reachable with `Run Flow`: the AI assertions (need a
Maestro Cloud key), `inputRandom*`, clipboard commands (the copied text stays inside one flow),
`repeat`/`retry` (use Robot's FOR and `Wait Until Keyword Succeeds`), `runScript`/`evalScript`,
`toggleAirplaneMode`, `assertDarkMode`/`assertLightMode`, `clearKeychain` (iOS), `doubleTapOn`.

Each `maestro mcp` process reinstalls Maestro's driver app on the device once, when it first
connects (Maestro hard-codes it). The library keeps one process for the whole run.

Tip: to let a coding agent look at the app while you write tests, register the same server with
it, e.g. `claude mcp add maestro -- maestro mcp` for Claude Code. It opens its own session on
the device, so keep it idle while a Robot run is going.
