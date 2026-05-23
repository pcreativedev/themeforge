import { NextRequest, NextResponse } from 'next/server';

// Licensing setup wizard guard.
//
// Reads a hint cookie set by the wizard on completion. The hint is only
// a UX shortcut — actual auth/authorization is still your job (Better
// Auth, NextAuth, etc.). The setup state lives client-side in localStorage
// (Zustand `__SLUG__-setup`); this cookie is set so server-side redirects
// can short-circuit the load.
const SETUP_COOKIE = '__SLUG__-setup-completed';

const PUBLIC_PATHS = [
  '/setup',
  '/api/verify-license',
  '/api/setup',
  '/_next',
  '/favicon.ico',
];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  const completed = req.cookies.get(SETUP_COOKIE)?.value === '1';
  if (!completed) {
    const url = req.nextUrl.clone();
    url.pathname = '/setup';
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)'],
};
