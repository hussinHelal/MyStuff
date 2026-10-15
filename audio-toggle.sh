#!/bin/bash

# Define your two audio devices (replace these with yours)
DEV1="alsa_output.pci-0000_00_1b.0.analog-stereo"
DEV2="alsa_output.pci-0000_28_00.1.hdmi-stereo"

# Get the current default audio sink
CURRENT=$(pactl info | awk -F': ' '/Default Sink/ {print $2}')

# Toggle target based on the current active device
if [ "$CURRENT" = "$DEV1" ]; then
    NEW_DEV="$DEV2"
    MSG="Audio switched to Device 2"
else
    NEW_DEV="$DEV1"
    MSG="Audio switched to Device 1"
fi

# Set the new default sink
pactl set-default-sink "$NEW_DEV"

# Move all currently playing audio streams to the new sink on-the-fly
for input in $(pactl list short sink-inputs | awk '{print $1}'); do
    pactl move-sink-input "$input" "$NEW_DEV"
done

# Optional: Send a desktop notification (requires notify-send installed)
if command -v notify-send &> /dev/null; then
    notify-send "Audio Output" "$MSG" --icon=notification-audio-volume-high
fi

