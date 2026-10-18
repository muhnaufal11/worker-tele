<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\Episode;

$ep = Episode::where('slug', 'doraemon-episode-367')->first();
if (!$ep) {
    echo "Not found\n";
    exit;
}

echo "Episode: " . $ep->id . " (" . $ep->slug . ")\n";
foreach ($ep->videoServers as $s) {
    echo "ID: " . $s->id . " | Name: " . $s->server_name . " | Audio: " . var_export($s->audio_type, true) . "\n";
}
