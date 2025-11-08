/**
 * Cloudflare Worker to proxy API requests to Cloud Run with access control
 * This keeps the custom domain in the browser while connecting to Cloud Run backend
 *
 * Security Features:
 *   - Blocks public access to /docs and /redoc
 *   - Validates Origin/Referer headers for API endpoints
 *   - Allows health check endpoint (/) to be public
 *   - Supports WebSocket connections with origin validation
 *
 * Environment Variables (set in Cloudflare Worker Settings):
 *   CLOUD_RUN_URL - The Cloud Run service URL (e.g., https://audio-api-5cuqeypfpq-ez.a.run.app)
 *   ALLOWED_ORIGINS - Comma-separated list of allowed origins (e.g., https://voiceia.danobhub.com,http://localhost:3202)
 *
 * Deploy this worker in Cloudflare and set the route to match your API domain
 */

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)

  // Get Cloud Run URL from environment variable or use default
  // TODO: Set CLOUD_RUN_URL as environment variable in Cloudflare Worker settings
  const cloudRunBaseUrl = typeof CLOUD_RUN_URL !== 'undefined'
    ? CLOUD_RUN_URL
    : 'https://audio-api-5cuqeypfpq-ez.a.run.app'

  // Get allowed origins from environment variable or use defaults
  const allowedOriginsStr = typeof ALLOWED_ORIGINS !== 'undefined'
    ? ALLOWED_ORIGINS
    : 'https://voiceia.danobhub.com,http://localhost:3202,http://voiceia.danobhub.local:3202'
  const allowedOrigins = allowedOriginsStr.split(',').map(o => o.trim())

  // --- WEBSOCKET HANDLING ---
  // Check if this is a WebSocket upgrade request
  const upgradeHeader = request.headers.get('Upgrade')
  if (upgradeHeader && upgradeHeader.toLowerCase() === 'websocket') {
    // For WebSocket, we need to pass through the connection without modification
    // Validate origin first
    const origin = request.headers.get('Origin')
    const isAllowedOrigin = origin && allowedOrigins.includes(origin)

    if (!isAllowedOrigin) {
      return new Response(JSON.stringify({
        error: 'Forbidden',
        message: 'WebSocket connection denied. Only authorized origins allowed.'
      }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    // For WebSocket connections, we need to construct the backend URL
    // and let Cloudflare handle the WebSocket upgrade
    const backendUrl = cloudRunBaseUrl + url.pathname + url.search

    // Create a new request with all original headers
    const newRequest = new Request(backendUrl, {
      method: request.method,
      headers: request.headers,
    })

    // Return the fetch response directly - Cloudflare will handle the WebSocket upgrade
    return fetch(newRequest)
  }

  // --- SECURITY CHECKS ---

  // 1. Block public access to API documentation
  const blockedPaths = ['/docs', '/redoc', '/openapi.json']
  if (blockedPaths.some(path => url.pathname === path || url.pathname.startsWith(path + '/'))) {
    return new Response(JSON.stringify({
      error: 'Forbidden',
      message: 'API documentation is not publicly accessible'
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' }
    })
  }

  // 2. Allow health check endpoint to be public (for monitoring)
  if (url.pathname === '/' || url.pathname === '/health' || url.pathname === '/healthz') {
    // Health check - allow without origin validation
    const cloudRunUrl = `${cloudRunBaseUrl}${url.pathname}${url.search}`
    const response = await fetch(cloudRunUrl, {
      method: request.method,
      headers: request.headers,
    })
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    })
  }

  // 3. Validate Origin/Referer for API endpoints
  const origin = request.headers.get('Origin')
  const referer = request.headers.get('Referer')

  // Check if request comes from allowed origin
  const isAllowedOrigin = origin && allowedOrigins.includes(origin)
  const isAllowedReferer = referer && allowedOrigins.some(allowed => referer.startsWith(allowed))

  if (!isAllowedOrigin && !isAllowedReferer) {
    return new Response(JSON.stringify({
      error: 'Forbidden',
      message: 'Access denied. API only accessible through authorized frontend applications.'
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' }
    })
  }

  // --- PROXY REQUEST TO CLOUD RUN ---

  // Build the Cloud Run API URL with path and query string
  const cloudRunUrl = `${cloudRunBaseUrl}${url.pathname}${url.search}`

  // Forward the request to Cloud Run with all headers
  const response = await fetch(cloudRunUrl, {
    method: request.method,
    headers: request.headers,
    body: request.method !== 'GET' && request.method !== 'HEAD' ? request.body : undefined,
  })

  // Return response with all CORS headers from backend
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  })
}
