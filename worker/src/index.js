// Cloudflare Worker: private, signed access to the R2 `media-private` bucket for
// the eo Swim viewer. It streams objects (with Range support so scrubbing works)
// only when the request carries a valid, unexpired signed token.
//
// Link form:
//   https://<worker-host>/<key>?e=<unix-expiry>&t=<token>
//   token = base64url( HMAC-SHA256( SIGNING_SECRET, "<key>\n<e>" ) )
//
// The SAME secret signs links on your PC (scripts/publish-to-r2.ps1), so no
// database is needed — the Worker just recomputes the HMAC and compares.
//
// Secret: set once with `wrangler secret put SIGNING_SECRET`.
// Binding: R2 bucket `media-private` as MEDIA (see wrangler.toml).

const enc = new TextEncoder();

function b64url(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sign(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64url(new Uint8Array(await crypto.subtle.sign('HMAC', key, enc.encode(message))));
}

// constant-time string compare (avoid leaking via timing)
function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

// CORS so the browser tools (edit.html / frames.html) can fetch the bytes too;
// plain <video> playback in the viewer doesn't need it, but ffmpeg.wasm does.
function cors(request) {
  const h = new Headers();
  const origin = request.headers.get('Origin');
  if (origin) {
    h.set('Access-Control-Allow-Origin', origin);
    h.set('Vary', 'Origin');
    h.set('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS');
    h.set('Access-Control-Allow-Headers', 'Range');
    h.set('Access-Control-Expose-Headers', 'Content-Length, Content-Range, Accept-Ranges, ETag');
  }
  return h;
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors(request) });
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405 });
    }

    const url = new URL(request.url);
    const key = decodeURIComponent(url.pathname.replace(/^\/+/, ''));
    if (!key) return new Response('Not found', { status: 404 });

    // ---- token check ----
    const e = url.searchParams.get('e') || '';
    const t = url.searchParams.get('t') || '';
    if (!/^\d+$/.test(e) || !t) return new Response('Missing or malformed token', { status: 401 });
    if (Number(e) < Math.floor(Date.now() / 1000)) return new Response('Link expired', { status: 410 });
    const expected = await sign(env.SIGNING_SECRET, key + '\n' + e);
    if (!safeEqual(expected, t)) return new Response('Invalid token', { status: 403 });

    // ---- serve from R2 ----
    const headers = cors(request);
    headers.set('Accept-Ranges', 'bytes');
    headers.set('Cache-Control', 'private, max-age=3600');

    if (request.method === 'HEAD') {
      const head = await env.MEDIA.head(key);
      if (!head) return new Response('Not found', { status: 404, headers });
      head.writeHttpMetadata(headers);
      headers.set('ETag', head.httpEtag);
      headers.set('Content-Length', String(head.size));
      return new Response(null, { status: 200, headers });
    }

    const object = await env.MEDIA.get(key, { range: request.headers });
    if (!object) return new Response('Not found', { status: 404, headers });
    object.writeHttpMetadata(headers);
    headers.set('ETag', object.httpEtag);

    if (object.range) {
      let off, len;
      if (object.range.suffix != null) { len = object.range.suffix; off = object.size - len; }
      else { off = object.range.offset || 0; len = object.range.length != null ? object.range.length : object.size - off; }
      headers.set('Content-Range', `bytes ${off}-${off + len - 1}/${object.size}`);
      headers.set('Content-Length', String(len));
      return new Response(object.body, { status: 206, headers });
    }
    headers.set('Content-Length', String(object.size));
    return new Response(object.body, { status: 200, headers });
  },
};
