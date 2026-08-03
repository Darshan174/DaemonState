import { onRequestPost as registerWaitlistSignup } from "../functions/api/waitlist.js";

function methodNotAllowed() {
  return new Response(null, {
    status: 405,
    headers: {
      allow: "POST",
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(request, env, context) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/waitlist") {
      return new Response(null, { status: 404 });
    }
    if (request.method !== "POST") {
      return methodNotAllowed();
    }

    return registerWaitlistSignup({
      request,
      env,
      waitUntil: context.waitUntil.bind(context),
    });
  },
};
