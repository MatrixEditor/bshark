// --- START OF AGENT SCRIPT ---
const libbinder = "libbinder.so"
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

function Descriptor(ptr) {
    return {
        ptr: ptr,
        get length() { return this.ptr.add(12).readU32(); },
        get name() { return this.ptr.add(16).readUtf16String(this.length); }
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
         * android::IPCThreadState::transact(int, unsigned int, android::Parcel const&, android::Parcel*, unsigned int)
         */
        onEnter: function (args) {
            console.log("\n[TRANSACTION] handle=" + args[0] + ", code=" + args[2] + ", data=" + args[3] + ", reply=" + args[4] + ", flags=" + args[5]);

            // There seems to be another parameter after the handle
            var dataPtr = args[3];
            this.parcel = Parcel64(dataPtr);

            var replyPtr = args[4];
            this.reply = Parcel64(replyPtr);
            this.code = args[2].toInt32();

            if (this.parcel.data.isNull()) {
                console.log(" | Data is NULL!");
                return;
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