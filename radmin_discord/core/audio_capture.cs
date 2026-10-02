using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.IO;

namespace RadCord.AudioHelper
{
    // --- Win32 / COM Glue ---

    [Guid("1CB9AD4E-5115-4597-ACA3-519B1D629598"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioClient {
        [PreserveSig] int Initialize(int shareMode, uint streamFlags, long hnsBufferDuration, long hnsPeriodicity, [In] ref WaveFormatEx pFormat, [In] ref Guid audioSessionGuid);
        [PreserveSig] int GetBufferSize(out uint pNumBufferFrames);
        [PreserveSig] int GetStreamLatency(out long phnsLatency);
        [PreserveSig] int GetCurrentPadding(out uint pNumPaddingFrames);
        [PreserveSig] int IsFormatSupported(int shareMode, [In] ref WaveFormatEx pFormat, out IntPtr ppClosestMatch);
        [PreserveSig] int GetMixFormat(out IntPtr ppDeviceFormat);
        [PreserveSig] int GetDevicePeriod(out long phnsDefaultDevicePeriod, out long phnsMinimumDevicePeriod);
        [PreserveSig] int Start();
        [PreserveSig] int Stop();
        [PreserveSig] int Reset();
        [PreserveSig] int SetEventHandle(IntPtr eventHandle);
        [PreserveSig] int GetService([In] ref Guid riid, [Out, MarshalAs(UnmanagedType.IUnknown)] out object ppv);
    }

    [Guid("C8ADBD64-E71E-48A0-A4DE-3DB745E245BA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioCaptureClient {
        [PreserveSig] int GetBuffer(out IntPtr ppData, out uint pNumFramesToRead, out uint pdwFlags, out long pu64DevicePosition, out long pu64QPCPosition);
        [PreserveSig] int ReleaseBuffer(uint numFramesRead);
        [PreserveSig] int GetNextPacketSize(out uint pNumFramesInNextPacket);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    struct WaveFormatEx {
        public ushort wFormatTag;
        public ushort nChannels;
        public uint nSamplesPerSec;
        public uint nAvgBytesPerSec;
        public ushort nBlockAlign;
        public ushort wBitsPerSample;
        public ushort cbSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct AudioClientActivationParams {
        public uint ActivationType; // 1 = Process Loopback
        public uint ProcessId;
        public uint ProcessLoopbackMode; // 0 = Include, 1 = Exclude
    }

    [ComImport, Guid("41D94F65-7128-4107-B696-654A71295E73"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceAsyncOperation {
        [PreserveSig] int GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
    }

    [ComImport, Guid("41BC3F7B-E6C8-4158-97F7-CCF3929D7D68"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceCompletionHandler {
        void ActivateCompleted(IActivateAudioInterfaceAsyncOperation activateOperation);
    }

    class CompletionHandler : IActivateAudioInterfaceCompletionHandler {
        public AutoResetEvent CompletedEvent = new AutoResetEvent(false);
        public IAudioClient Client;
        public int Result;

        public void ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation) {
            object iface;
            operation.GetActivateResult(out Result, out iface);
            Client = iface as IAudioClient;
            CompletedEvent.Set();
        }
    }

    class Program {
        [DllImport("Mmdevapi.dll", ExactSpelling = true, PreserveSig = true)]
        static extern int ActivateAudioInterfaceAsync(
            [MarshalAs(UnmanagedType.LPWStr)] string deviceInterfacePath,
            [In] ref Guid riid,
            [In] IntPtr activationParams,
            [In] IActivateAudioInterfaceCompletionHandler completionHandler,
            out IActivateAudioInterfaceAsyncOperation activationOperation);

        [STAThread]
        static void Main(string[] args) {
            if (args.Length < 2) {
                Console.Error.WriteLine("Usage: audio_capture.exe <PID> <Mode: 0=Include, 1=Exclude>");
                return;
            }

            uint pid = uint.Parse(args[0]);
            uint mode = uint.Parse(args[1]);

            var handler = new CompletionHandler();
            var guidIidAudioClient = new Guid("1CB9AD4E-5115-4597-ACA3-519B1D629598");
            
            var paramsStruct = new AudioClientActivationParams {
                ActivationType = 1,
                ProcessId = pid,
                ProcessLoopbackMode = mode
            };

            IntPtr ptrParams = Marshal.AllocHGlobal(Marshal.SizeOf(paramsStruct));
            Marshal.StructureToPtr(paramsStruct, ptrParams, false);

            IActivateAudioInterfaceAsyncOperation op;
            int hr = ActivateAudioInterfaceAsync("VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK", ref guidIidAudioClient, ptrParams, handler, out op);

            if (hr < 0) {
                Console.Error.WriteLine("ActivateAudioInterfaceAsync failed: 0x{0:X}", hr);
                return;
            }

            handler.CompletedEvent.WaitOne(5000);
            if (handler.Client == null) {
                Console.Error.WriteLine("Activation failed or timed out. HR: 0x{0:X}", handler.Result);
                return;
            }

            IAudioClient client = handler.Client;
            WaveFormatEx format = new WaveFormatEx {
                wFormatTag = 1, // PCM
                nChannels = 1,
                nSamplesPerSec = 48000,
                wBitsPerSample = 16,
                nBlockAlign = 2,
                nAvgBytesPerSec = 48000 * 2,
                cbSize = 0
            };

            Guid sessionGuid = Guid.Empty;
            hr = client.Initialize(0, 0x00020000, 1000000, 0, ref format, ref sessionGuid);
            if (hr < 0) {
                Console.Error.WriteLine("IAudioClient.Initialize failed: 0x{0:X}", hr);
                return;
            }

            object captureObj;
            Guid guidCaptureClient = new Guid("C8ADBD64-E71E-48A0-A4DE-3DB745E245BA");
            client.GetService(ref guidCaptureClient, out captureObj);
            IAudioCaptureClient capture = captureObj as IAudioCaptureClient;

            client.Start();

            var stdout = Console.OpenStandardOutput();
            byte[] outBuf = new byte[4096];

            while (true) {
                uint nextPacketSize;
                capture.GetNextPacketSize(out nextPacketSize);
                if (nextPacketSize == 0) {
                    Thread.Sleep(5);
                    continue;
                }

                IntPtr data;
                uint frames;
                uint flags;
                long pos, qpc;
                capture.GetBuffer(out data, out frames, out flags, out pos, out qpc);

                int bytes = (int)(frames * 2);
                if (outBuf.Length < bytes) outBuf = new byte[bytes];
                Marshal.Copy(data, outBuf, 0, bytes);
                stdout.Write(outBuf, 0, bytes);

                capture.ReleaseBuffer(frames);
            }
        }
    }
}
