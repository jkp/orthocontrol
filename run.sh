PATHPROJECT=$(dirname "$0")
. $PATHPROJECT"/env/bin/activate"
python3 $PATHPROJECT"/orthocontrol.py" --midi-name="ortho remote Bluetooth"