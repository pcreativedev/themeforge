<?php

namespace App\Http\Middleware;

use App\Models\SetupState;
use Closure;
use Illuminate\Http\Request;

class CheckSetupWizard
{
    public function handle(Request $request, Closure $next)
    {
        // Las rutas del wizard y assets quedan siempre accesibles.
        if (
            $request->is('install*') ||
            $request->is('build/*') ||
            $request->is('storage/*') ||
            $request->is('_ignition/*')
        ) {
            return $next($request);
        }

        try {
            $state = SetupState::query()->first();
            if (!$state || !$state->installed_at) {
                return redirect()->route('setup.index');
            }
        } catch (\Throwable $e) {
            // Tabla aún no migrada → manda al wizard.
            return redirect()->route('setup.index');
        }

        return $next($request);
    }
}
