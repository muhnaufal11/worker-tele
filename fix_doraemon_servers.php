<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\VideoServer;

// 1. Delete test duplicate server
VideoServer::where('id', 1150851)->delete();

// 2. Correct 1150791 (1080p) to Dub
$s1080 = VideoServer::find(1150791);
if ($s1080) {
    $s1080->update([
        'server_name' => 'Nipnime Stream [Cloud 1080p Dub]',
        'audio_type' => 'dub',
    ]);
    echo "Server 1150791 updated to Dub\n";
}

// 3. Correct 1150826 (720p) to Dub
$s720 = VideoServer::find(1150826);
if ($s720) {
    $s720->update([
        'server_name' => 'Nipnime Stream [Cloud 720p Dub]',
        'audio_type' => 'dub',
    ]);
    echo "Server 1150826 updated to Dub\n";
}

echo "Doraemon episode 367 servers fixed!\n";
