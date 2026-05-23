<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('setup_state', function (Blueprint $table) {
            $table->id();
            $table->string('license_key')->nullable();
            $table->timestamp('installed_at')->nullable();
            $table->string('installed_domain')->nullable();
            $table->json('meta')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('setup_state');
    }
};
