<?php

namespace App\Http\Controllers;

use App\Models\SetupState;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Http;

class SetupWizardController extends Controller
{
    // License endpoint + product slug for this theme.
    private const LICENSE_API_URL = '__LICENSE_API_URL__';
    private const PRODUCT_SLUG    = '__SLUG__';

    public function index()
    {
        if ($this->isInstalled()) {
            return redirect('/');
        }
        return view('setup.index', [
            'projectName' => config('app.name', '__PROJECT__'),
            'productSlug' => self::PRODUCT_SLUG,
        ]);
    }

    public function verifyLicense(Request $request)
    {
        $request->validate(['license_key' => 'required|string']);

        try {
            $res = Http::timeout(10)->post(self::LICENSE_API_URL, [
                'license_key' => $request->license_key,
                'product'     => self::PRODUCT_SLUG,
                'domain'      => $request->getHost(),
            ]);
            $data = $res->json();
        } catch (\Throwable $e) {
            // Graceful fallback: aceptar provisionalmente si el servidor
            // de licencias está caído, para no bloquear la instalación.
            $data = ['valid' => true, '_warning' => 'License server unreachable.'];
        }

        if (!($data['valid'] ?? false)) {
            return response()->json([
                'valid' => false,
                'error' => $data['error'] ?? 'Invalid license.',
            ], 422);
        }

        // Persistimos la clave en setup_state, todavía sin marcar como
        // instalado (eso ocurre cuando termine el wizard).
        SetupState::query()->updateOrCreate(
            ['id' => 1],
            [
                'license_key'       => $request->license_key,
                'installed_domain'  => $request->getHost(),
                'meta'              => array_filter([
                    'license_data' => $data,
                ]),
            ]
        );

        return response()->json(['valid' => true, 'data' => $data]);
    }

    public function testDatabase()
    {
        try {
            DB::connection()->getPdo();
            return response()->json(['ok' => true]);
        } catch (\Throwable $e) {
            return response()->json([
                'ok'    => false,
                'error' => $e->getMessage(),
            ], 422);
        }
    }

    public function migrate()
    {
        Artisan::call('migrate', ['--force' => true]);
        $output = Artisan::output();

        if (class_exists(\Database\Seeders\DemoSeeder::class)) {
            Artisan::call('db:seed', [
                '--class' => 'DemoSeeder',
                '--force' => true,
            ]);
            $output .= "\n" . Artisan::output();
        }
        return response()->json(['ok' => true, 'output' => $output]);
    }

    public function createAdmin(Request $request)
    {
        $data = $request->validate([
            'name'     => 'required|string|max:120',
            'email'    => 'required|email',
            'password' => 'required|string|min:8',
        ]);

        $user = User::query()->updateOrCreate(
            ['email' => $data['email']],
            [
                'name'              => $data['name'],
                'password'          => Hash::make($data['password']),
                'email_verified_at' => now(),
            ]
        );

        // Marcar como instalado para que el middleware deje de redirigir.
        SetupState::query()->updateOrCreate(
            ['id' => 1],
            ['installed_at' => now()]
        );

        return response()->json(['ok' => true, 'user_id' => $user->id]);
    }

    private function isInstalled(): bool
    {
        try {
            $state = SetupState::query()->first();
            return $state && $state->installed_at;
        } catch (\Throwable $e) {
            return false;
        }
    }
}
