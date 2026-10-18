<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\Anime;

$animes = Anime::select('id', 'title', 'title_en', 'mal_id', 'slug')->get();
file_put_contents(__DIR__ . '/all_anime_db.json', $animes->toJson(JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
echo "Exported " . $animes->count() . " animes to all_anime_db.json\n";
