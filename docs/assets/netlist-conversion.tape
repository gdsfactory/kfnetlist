# Renders the README GIF. From the repository root, with the dev environment built:
#   brew install vhs && vhs docs/assets/netlist-conversion.tape
# Keep the GIF under 500 KB (pre-commit check-added-large-files).

Output docs/assets/netlist-conversion.gif

Set Shell "bash"
Set FontSize 15
Set Width 1000
Set Height 560
Set Padding 20
Set Framerate 12
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Hide
Type "source .venv/bin/activate && cd docs/assets && clear" Enter
Show

Type "cat inverter.scs" Enter
Sleep 2s

Type "python convert_demo.py spectre vams < inverter.scs" Enter
Sleep 3s

Type "python convert_demo.py spectre spice < inverter.scs | python convert_demo.py spice spectre" Enter
Sleep 4s
