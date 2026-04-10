import wave
import struct
import math
import os

def generate_beep(filename, freq=440.0, duration=0.1, volume=0.5, samplerate=44100):
    """Generates a simple sine wave beep."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    num_samples = int(duration * samplerate)
    
    with wave.open(filename, 'w') as wav:
        wav.setnchannels(1) # Mono
        wav.setsampwidth(2) # 16-bit
        wav.setframerate(samplerate)
        
        for i in range(num_samples):
            # Fade in/out to avoid clicks
            fade = 1.0
            if i < 400: fade = i / 400.0
            if i > num_samples - 400: fade = (num_samples - i) / 400.0
            
            sample = volume * fade * math.sin(2 * math.pi * freq * (i / samplerate))
            encoded = struct.pack('<h', int(sample * 32767))
            wav.writeframesraw(encoded)

if __name__ == "__main__":
    base_dir = os.path.join(os.getcwd(), "assets", "sounds")
    # Mute: slightly lower, Unmute: higher pitch
    generate_beep(os.path.join(base_dir, "mute.wav"), freq=400, duration=0.1, volume=0.8)
    generate_beep(os.path.join(base_dir, "unmute.wav"), freq=800, duration=0.1, volume=0.8)
    # Deafen: double beep or similar, or just distinct tones
    generate_beep(os.path.join(base_dir, "deafen.wav"), freq=300, duration=0.15, volume=0.8)
    generate_beep(os.path.join(base_dir, "undeafen.wav"), freq=900, duration=0.15, volume=0.8)
    print(f"Sounds generated in {base_dir}")
