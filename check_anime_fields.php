<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\Anime;

$first = Anime::first();
echo "Sample Anime:\n";
echo "Status: " . $first->status . "\n";
echo "Type: " . $first->type . "\n";
echo "Season: " . $first->season . "\n";

$statuses = Anime::select('status')->distinct()->pluck('status');
echo "Distinct statuses: " . json_encode($statuses) . "\n";
