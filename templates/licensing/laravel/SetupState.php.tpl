<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class SetupState extends Model
{
    protected $table = 'setup_state';

    protected $fillable = [
        'license_key',
        'installed_at',
        'installed_domain',
        'meta',
    ];

    protected $casts = [
        'installed_at' => 'datetime',
        'meta'         => 'array',
    ];
}
