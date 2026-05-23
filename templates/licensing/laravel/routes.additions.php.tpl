
// ─── licensing setup wizard ──────────────────────────────────────────
use App\Http\Controllers\SetupWizardController;

Route::prefix('install')->group(function () {
    Route::get('/',         [SetupWizardController::class, 'index'])->name('setup.index');
    Route::post('verify',   [SetupWizardController::class, 'verifyLicense']);
    Route::post('database', [SetupWizardController::class, 'testDatabase']);
    Route::post('migrate',  [SetupWizardController::class, 'migrate']);
    Route::post('admin',    [SetupWizardController::class, 'createAdmin']);
});
