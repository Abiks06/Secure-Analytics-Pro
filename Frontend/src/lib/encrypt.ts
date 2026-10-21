/**
 * Client-side encryption of uploads (Web Crypto, AES-256-GCM).
 *
 * Produces exactly the engine's "SAP1" chunked format (Backend/app/core/crypto.py):
 *   "SAP1" || for each 4 MiB chunk: u32be(len(ct)) || nonce(12) || ct(with 16-byte tag)
 * Each chunk authenticates  context || u32be(index) || u8(is_last), so chunks can't be
 * reordered, dropped or truncated. The key is random per upload, never stored, and sent to the
 * engine only over TLS when processing starts.
 */

const CHUNK = 4 * 1024 * 1024;
const MAGIC = new TextEncoder().encode("SAP1");

export interface EncryptedUpload {
  blob: Blob;
  keyB64: string;
}

function toB64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export async function encryptForUpload(file: File, context: string): Promise<EncryptedUpload> {
  const raw = crypto.getRandomValues(new Uint8Array(32));
  const key = await crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt"]);
  const ctx = new TextEncoder().encode(context);
  const total = Math.max(1, Math.ceil(file.size / CHUNK));
  const parts: BlobPart[] = [MAGIC];
  for (let i = 0; i < total; i++) {
    const plain = new Uint8Array(await file.slice(i * CHUNK, (i + 1) * CHUNK).arrayBuffer());
    const aad = new Uint8Array(ctx.length + 5);
    aad.set(ctx);
    new DataView(aad.buffer).setUint32(ctx.length, i, false);
    aad[ctx.length + 4] = i === total - 1 ? 1 : 0;
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: aad }, key, plain));
    const header = new Uint8Array(4);
    new DataView(header.buffer).setUint32(0, ct.length, false);
    parts.push(header, nonce, ct);
  }
  const keyB64 = toB64(raw);
  raw.fill(0);
  return { blob: new Blob(parts, { type: "application/octet-stream" }), keyB64 };
}
