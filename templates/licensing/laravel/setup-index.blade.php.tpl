<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <title>Setup · {{ $projectName }}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center p-6">
<div x-data="setupWizard()" class="w-full max-w-2xl bg-white rounded-2xl shadow p-8 space-y-6">

  <header>
    <h1 class="text-3xl font-bold">{{ $projectName }}</h1>
    <p class="text-gray-500">Setup wizard</p>
  </header>

  {{-- Stepper --}}
  <ol class="flex items-center justify-between text-sm">
    <template x-for="(s, i) in steps" :key="s.key">
      <li class="flex-1" :class="s.key === current ? 'font-bold text-black' : 'text-gray-400'">
        <span class="block" x-text="s.label"></span>
      </li>
    </template>
  </ol>

  {{-- Step: welcome --}}
  <section x-show="current === 'welcome'" x-cloak class="space-y-4">
    <p>Para empezar, introduce tu clave de licencia.</p>
    <input type="text" x-model="licenseKey"
           class="w-full border rounded-lg px-3 py-2"
           placeholder="XXXX-XXXX-XXXX-XXXX">
    <p x-show="error" x-text="error" class="text-red-600 text-sm"></p>
    <button @click="verifyLicense()" :disabled="loading || !licenseKey"
            class="w-full bg-black text-white py-3 rounded-lg disabled:opacity-50">
      <span x-text="loading ? 'Verificando…' : 'Verificar y continuar'"></span>
    </button>
  </section>

  {{-- Step: database --}}
  <section x-show="current === 'database'" x-cloak class="space-y-4">
    <p>Comprobamos la conexión a la base de datos definida en <code>.env</code>.</p>
    <p x-show="error" x-text="error" class="text-red-600 text-sm"></p>
    <button @click="testDatabase()" :disabled="loading"
            class="w-full bg-black text-white py-3 rounded-lg">
      <span x-text="loading ? 'Probando…' : 'Probar conexión y continuar'"></span>
    </button>
  </section>

  {{-- Step: migrate --}}
  <section x-show="current === 'migrate'" x-cloak class="space-y-4">
    <p>Ejecutar migraciones y seeder de demostración.</p>
    <p x-show="error" x-text="error" class="text-red-600 text-sm"></p>
    <pre x-show="output" x-text="output" class="bg-gray-100 text-xs p-2 rounded overflow-auto max-h-40"></pre>
    <button @click="runMigrate()" :disabled="loading"
            class="w-full bg-black text-white py-3 rounded-lg">
      <span x-text="loading ? 'Migrando…' : 'Migrar y continuar'"></span>
    </button>
  </section>

  {{-- Step: admin --}}
  <section x-show="current === 'admin'" x-cloak class="space-y-4">
    <p>Crear el primer usuario administrador.</p>
    <input type="text" x-model="admin.name" placeholder="Nombre"
           class="w-full border rounded-lg px-3 py-2">
    <input type="email" x-model="admin.email" placeholder="admin@example.com"
           class="w-full border rounded-lg px-3 py-2">
    <input type="password" x-model="admin.password" placeholder="Contraseña (≥ 8)"
           class="w-full border rounded-lg px-3 py-2">
    <p x-show="error" x-text="error" class="text-red-600 text-sm"></p>
    <button @click="createAdmin()" :disabled="loading"
            class="w-full bg-black text-white py-3 rounded-lg">
      <span x-text="loading ? 'Creando…' : 'Crear admin y terminar'"></span>
    </button>
  </section>

  {{-- Step: complete --}}
  <section x-show="current === 'complete'" x-cloak class="text-center space-y-3">
    <p class="text-2xl">Listo.</p>
    <a href="/" class="inline-block bg-black text-white py-3 px-6 rounded-lg">
      Entrar a la app
    </a>
  </section>

</div>

<script>
function setupWizard() {
  return {
    csrf: document.querySelector('meta[name=csrf-token]').content,
    steps: [
      { key: 'welcome',  label: '1. Licencia' },
      { key: 'database', label: '2. Base de datos' },
      { key: 'migrate',  label: '3. Migrar' },
      { key: 'admin',    label: '4. Admin' },
      { key: 'complete', label: '5. Listo' },
    ],
    current: 'welcome',
    licenseKey: '',
    admin: { name: '', email: '', password: '' },
    loading: false,
    error: null,
    output: '',
    async _post(path, body) {
      const res = await fetch(path, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-CSRF-TOKEN': this.csrf,
        },
        body: JSON.stringify(body || {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
      return data;
    },
    async verifyLicense() {
      this.loading = true; this.error = null;
      try {
        await this._post('/install/verify', { license_key: this.licenseKey });
        this.current = 'database';
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },
    async testDatabase() {
      this.loading = true; this.error = null;
      try {
        await this._post('/install/database', {});
        this.current = 'migrate';
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },
    async runMigrate() {
      this.loading = true; this.error = null;
      try {
        const r = await this._post('/install/migrate', {});
        this.output = r.output || '';
        this.current = 'admin';
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },
    async createAdmin() {
      this.loading = true; this.error = null;
      try {
        await this._post('/install/admin', this.admin);
        this.current = 'complete';
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },
  };
}
</script>

</body>
</html>
