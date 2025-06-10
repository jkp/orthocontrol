#!/usr/bin/env python3
"""Quick MIDI port diagnostic tool"""

import rtmidi

def main():
    print("=== MIDI Port Diagnostic ===\n")
    
    # Check MIDI inputs
    midi_in = rtmidi.MidiIn()
    input_ports = midi_in.get_ports()
    
    print(f"Available MIDI Input Ports ({len(input_ports)}):")
    if input_ports:
        for i, port in enumerate(input_ports):
            print(f"  [{i}] {port}")
    else:
        print("  No MIDI input ports found!")
    
    print()
    
    # Check MIDI outputs
    midi_out = rtmidi.MidiOut()
    output_ports = midi_out.get_ports()
    
    print(f"Available MIDI Output Ports ({len(output_ports)}):")
    if output_ports:
        for i, port in enumerate(output_ports):
            print(f"  [{i}] {port}")
    else:
        print("  No MIDI output ports found!")
    
    print("\n=== Looking for 'ortho remote' ===")
    ortho_found = False
    for port in input_ports:
        if 'ortho remote' in port.lower():
            print(f"✓ Found in inputs: {port}")
            ortho_found = True
    
    for port in output_ports:
        if 'ortho remote' in port.lower():
            print(f"✓ Found in outputs: {port}")
            ortho_found = True
    
    if not ortho_found:
        print("✗ No 'ortho remote' device found in any ports")
        print("\nPossible issues:")
        print("- Device not connected via Bluetooth")
        print("- Device using different name")
        print("- MIDI server needs restart")

if __name__ == "__main__":
    main()