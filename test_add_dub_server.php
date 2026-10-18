<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\Episode;
use App\Models\VideoServer;

$ep = Episode::where('slug', 'doraemon-episode-367')->first();
if (!$ep) {
    echo "Episode not found\n";
    exit(1);
}

// Find existing 720p server to clone as Dub test
$existing = $ep->videoServers()->where('source', 'telegram')->first();
if ($existing) {
    $dub = VideoServer::firstOrCreate([
        'episode_id' => $ep->id,
        'server_name' => 'Nipnime Stream [Cloud 720p Dub]',
    ], [
        'source' => 'telegram',
        'embed_url' => $existing->embed_url,
        'quality' => '720p',
        'audio_type' => 'dub',
        'is_active' => true,
        'is_default' => false,
    ]);
    echo "Dub server ready: ID " . $dub->id . " (" . $dub->server_name . ")\n";
}
