# UI modernization

Owner: issue #11 (`cursor-20261124-ui-01`).

## Goals

- Consistent spacing, type scale, semantic status colors, and focus styling.
- Accessible status text so state never depends on color alone.
- Network intelligence and optional local-AI panels that degrade clearly when
  backends are absent from the integration base.
- Worker scheduling with cancellation, close-safe teardown, and stale-response
  suppression owned by the UI layer.

## Optional backend imports

The UI calls these only through optional resolvers:

- `optimizer.network_intelligence.analyze(snapshot)`
- `optimizer.ai.recommend(snapshot, network_result=None, *, cancel=None)`

When a module is missing, the panel shows an explicit **unavailable** /
**insufficient** state and keeps diagnostics usable. Tests inject fake
providers instead of touching host/network/model runtimes.

## Manual QA checklist

Record screenshots under a local `data/ui-preview/` folder (not committed):

1. Window at **1280×720**, **100%**, **150%**, and **200%** display scaling.
2. Keyboard-only path: Tab through sidebar → Overview controls → Network tabs →
   Local AI advice. Confirm visible focus rings and accessible status labels.
3. Confirm action dialogs still require explicit Yes/No before host changes.
4. With backends absent: Network → Intelligence and Local AI advice show clear
   unavailable/insufficient copy (not a blank panel).
5. Close the window during a fake slow advisory provider; late callbacks must
   not raise or overwrite newer UI state.

## Automated checks

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_gui.py tests/test_ai_ui.py -q
# Issue-requested discover form (TestCase modules):
python -m unittest discover -s tests -p test_gui.py
python -m unittest discover -s tests -p test_ai_ui.py
```
