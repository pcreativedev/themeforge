import { NextRequest, NextResponse } from 'next/server';

const LICENSE_API_URL = '__LICENSE_API_URL__';
const PRODUCT_SLUG = '__SLUG__';

export async function POST(req: NextRequest) {
  try {
    const { license_key, product, domain } = await req.json();
    if (!license_key) {
      return NextResponse.json(
        { valid: false, error: 'Purchase code is required' },
        { status: 400 }
      );
    }

    const res = await fetch(LICENSE_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        license_key,
        product: product || PRODUCT_SLUG,
        domain: domain || req.headers.get('host') || 'localhost',
      }),
    });

    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json(
      { valid: false, error: 'Unable to verify license. Try again later.' },
      { status: 500 }
    );
  }
}
