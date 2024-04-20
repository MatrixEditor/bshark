// --- START OF AGENT SCRIPT ---
// MIT License
//
// Copyright (c) 2024 MatrixEditor
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

const libbinder = "libbinder.so"
const x86 = (Process.arch == "ia32" || Process.arch == "arm");
var ANDROID_VERSION = 12;
var VERBOSE = false;

rpc.exports = {
    configure: function (stage, args) {
        ANDROID_VERSION = args.version;
        VERBOSE = args.verbose || true;
    }
};

/**
 * The structure was taken from here:
 * https://android.googlesource.com/platform/frameworks/native/+/refs/heads/main/libs/binder/include/binder/Parcel.h
 *
 * @param {NativePointer} ptr the pointer to a Parcel object
 */
function Parcel64(ptr) {
    return {
        ptr: ptr,
        get error() { return this.ptr.readU64(); },
        get data() { return this.ptr.add(8).readPointer(); },
        get dataSize() { return this.ptr.add(16).readU64(); },
        get dataCapacity() { return this.ptr.add(24).readU64(); },
        get dataPos() { return this.ptr.add(32).readU64(); },
        get rawData() { return this.data.readByteArray(this.dataSize); }
    }
}

function Parcel32(ptr) {
    return {
        ptr: ptr,
        get error() { return this.ptr.readU32(); },
        get data() { return this.ptr.add(4).readPointer(); },
        get dataSize() { return this.ptr.add(8).readU32(); },
        get dataCapacity() { return this.ptr.add(12).readU32(); },
        get dataPos() { return this.ptr.add(16).readU32(); },
        get rawData() { return this.data.readByteArray(this.dataSize); }
    }
}


function Descriptor(ptr) {
    return {
        ptr: ptr,
        get length() { return this.ptr.add(12).readU32(); },
        get name() {
            var pos = ANDROID_VERSION >= 10 ? 16 : 8;
            return this.ptr.add(pos).readUtf16String(this.length);
        }
    }
}

Interceptor.attach(
    Module.getExportByName(
        libbinder,
        "_ZN7android14IPCThreadState8transactEijRKNS_6ParcelEPS1_j"
    ),
    {
        reply: ptr("0x0"),
        parcel: ptr("0x0"),
        code: 0x0,
        descriptor: "",

        /**
         * The function signature is: (at least for Android 12)
         *
         * android::IPCThreadState::transact(
         *      int,
         *      unsigned int,
         *      android::Parcel const&,
         *      android::Parcel*,
         *      unsigned int
         * );
         */
        onEnter: function (args) {
            if (VERBOSE) {
                console.log(
                    "\n[TRANSACTION] arg0=" + args[0]
                    + ", handle=" + args[1]
                    + ", code=" + args[2]
                    + ", data=" + args[3]
                    + ", reply=" + args[4]
                    + ", flags=" + args[5]
                );
            }

            // There seems to be another parameter after the handle
            var dataPtr = args[3];
            this.parcel = x86 ? Parcel64(dataPtr) : Parcel32(dataPtr);

            var replyPtr = args[4];
            this.reply = x86 ? Parcel64(replyPtr) : Parcel32(replyPtr);
            this.code = args[2].toInt32();

            if (this.parcel.data.isNull()) {
                if (VERBOSE) console.log(" | Data is NULL!");
                return; // REVISIT: maybe include errors
            }
            var interfaceName = Descriptor(this.parcel.data);
            this.descriptor = interfaceName.name;
            send({
                "code": this.code,
                "descriptor": interfaceName.name,
                "type": "bshark_transaction_start"
            }, this.parcel.ptr.isNull() ? null : this.parcel.rawData)
        },

        onLeave: function (args) {
            send({
                "code": this.code,
                "descriptor": this.descriptor,
                "type": "bshark_transaction_reply"
            }, this.reply.ptr.isNull() ? null : this.reply.rawData)
            this.reply = ptr(0);
            this.parcel = ptr(0);
        }
    }
)

// --- END OF AGENT SCRIPT ---