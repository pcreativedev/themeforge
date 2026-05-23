'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useSetupStore } from '@/store/setup-store';

const PRODUCT_NAME = '__PROJECT__';
const PURCHASE_URL =
  process.env.NEXT_PUBLIC_PURCHASE_URL || 'https://gumroad.com';

export default function SetupPage() {
  const router = useRouter();
  const {
    currentStep,
    setStep,
    setLicense,
    setDatabaseTested,
    setAdminCreated,
    complete,
  } = useSetupStore();

  const [licenseKey, setLicenseKey] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verifyLicense() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/verify-license', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: licenseKey }),
      });
      const data = await res.json();
      if (!data.valid) {
        setError(data.error || 'Invalid license');
        return;
      }
      setLicense(licenseKey, data);
      setStep('database');
    } catch {
      setError('Could not contact license server.');
    } finally {
      setLoading(false);
    }
  }

  async function testDatabase() {
    setLoading(true);
    setError(null);
    try {
      // TODO: implement /api/setup/database that calls a real connection test
      await new Promise((r) => setTimeout(r, 400));
      setDatabaseTested(true);
      setStep('admin');
    } finally {
      setLoading(false);
    }
  }

  async function createAdmin() {
    setLoading(true);
    setError(null);
    try {
      // TODO: implement /api/setup/admin that creates the first user via Better-Auth
      if (!adminEmail || !adminPassword) {
        setError('Email and password required');
        return;
      }
      await new Promise((r) => setTimeout(r, 400));
      setAdminCreated(true);
      complete();
      router.push('/dashboard');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow p-8 space-y-6">
        <header>
          <h1 className="text-3xl font-bold">{PRODUCT_NAME}</h1>
          <p className="text-gray-500">Setup wizard</p>
        </header>

        <Steps current={currentStep} />

        {currentStep === 'welcome' && (
          <section className="space-y-4">
            <p>
              Welcome. To start using {PRODUCT_NAME} you need a valid
              license key. If you don&apos;t have one,{' '}
              <a className="text-blue-600 underline" href={PURCHASE_URL}>
                buy it here
              </a>
              .
            </p>
            <input
              className="w-full border rounded-lg px-3 py-2"
              placeholder="XXXX-XXXX-XXXX-XXXX"
              value={licenseKey}
              onChange={(e) => setLicenseKey(e.target.value)}
            />
            {error && <p className="text-red-600 text-sm">{error}</p>}
            <button
              className="w-full bg-black text-white py-3 rounded-lg disabled:opacity-50"
              onClick={verifyLicense}
              disabled={loading || !licenseKey}
            >
              {loading ? 'Verifying…' : 'Verify & continue'}
            </button>
          </section>
        )}

        {currentStep === 'database' && (
          <section className="space-y-4">
            <p>
              Your <code>DATABASE_URL</code> is configured in <code>.env</code>.
              We&apos;ll run a quick connection test.
            </p>
            {error && <p className="text-red-600 text-sm">{error}</p>}
            <button
              className="w-full bg-black text-white py-3 rounded-lg"
              onClick={testDatabase}
              disabled={loading}
            >
              {loading ? 'Testing…' : 'Test connection & continue'}
            </button>
          </section>
        )}

        {currentStep === 'admin' && (
          <section className="space-y-4">
            <p>Create the first admin user.</p>
            <input
              className="w-full border rounded-lg px-3 py-2"
              placeholder="admin@example.com"
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
            />
            <input
              className="w-full border rounded-lg px-3 py-2"
              type="password"
              placeholder="Password"
              value={adminPassword}
              onChange={(e) => setAdminPassword(e.target.value)}
            />
            {error && <p className="text-red-600 text-sm">{error}</p>}
            <button
              className="w-full bg-black text-white py-3 rounded-lg"
              onClick={createAdmin}
              disabled={loading}
            >
              {loading ? 'Creating…' : 'Create admin & finish'}
            </button>
          </section>
        )}

        {currentStep === 'launch' && (
          <section className="text-center space-y-3">
            <p className="text-2xl">All set.</p>
            <p>Redirecting to your dashboard…</p>
          </section>
        )}
      </div>
    </div>
  );
}

function Steps({ current }: { current: string }) {
  const steps: Array<{ key: string; label: string }> = [
    { key: 'welcome', label: '1. License' },
    { key: 'database', label: '2. Database' },
    { key: 'admin', label: '3. Admin' },
    { key: 'launch', label: '4. Launch' },
  ];
  return (
    <ol className="flex items-center justify-between text-sm">
      {steps.map((s, i) => {
        const active = s.key === current;
        return (
          <li
            key={s.key}
            className={
              'flex-1 ' +
              (active ? 'font-bold text-black' : 'text-gray-400')
            }
          >
            <span className="block">{s.label}</span>
            {i < steps.length - 1 && (
              <span className="block h-1 mt-2 bg-gray-200 rounded" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
