<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Http\Controllers\Api\TeropWorkerController;

$controller = new TeropWorkerController();

$testTitles = [
    'Kehidupan Santai di Dunia Lain dengan Kekuatan Ngecheat dari Level 2 - Eps 01 [Takarir Indonesia]',
    'Kehidupan Santai di Dunia Lain dengan Kekuatan Ngecheat dari Level 2 - Eps 01 [Bahasa Indonesia]',
    'Tongkat Sihir dan Pedang Wistoria - Episode 01 [Takarir Indonesia]',
    'Tongkat Sihir dan Pedang Wistoria - Episode 01 [Bahasa Indonesia]',
    'DAN DA DAN - Episode 01 [Takarir Indonesia]',
    'DAN DA DAN - Episode 01 [Sulih Suara]',
    'Arwah Berduka yang Ingin Pensiun ~ Jurus Pemburu Terlemah dalam Membina Grup Terkuat ~ - Episode 01 [Bahasa Indonesia]',
    'Arwah Berduka yang Ingin Pensiun ~ Jurus Pemburu Terlemah dalam Membina Grup Terkuat ~ - Episode 01 [Takarir Indonesia]',
    'Penguasa Misteri - Episode 01 [Takarir Indonesia|Bahasa Mandarin]',
    'Gacha Tak Hingga - Episode 01 [Takarir Indonesia]',
    'Om-om yang Bereinkarnasi Menjadi Putri Jahat - Episode 01 [Takarir Indonesia]',
    'Reborn! - Episode 01 [Takarir Indonesia]',
    'KAIJU DARA CARAMELISE - Episode 01 [Takarir Indonesia]',
    'Gambar Ini, Lalu Mati Sana! - Episode 01 [Takarir Indonesia]',
];

$reflection = new ReflectionClass($controller);
$findMethod = $reflection->getMethod('findMatchingAnime');
$findMethod->setAccessible(true);

echo "=========================================================\n";
echo "UJI COBA DETEKSI SUB INDO VS DUB INDO & PENCOCOKAN EPISODE\n";
echo "=========================================================\n\n";

$pass = 0;
foreach ($testTitles as $title) {
    $parsed = $controller->parseYouTubeTitle($title);
    $match = $findMethod->invoke(
        $controller,
        $parsed['clean_title'],
        $parsed['season'],
        $parsed['part'],
        $parsed['franchise_hint']
    );

    $anime = $match['anime'] ?? null;
    $status = $anime ? "✅ MATCH" : "❌ FAIL";
    if ($anime) $pass++;

    echo "Input  : {$title}\n";
    echo "Parsed : [Clean: '{$parsed['clean_title']}'] [Ep: {$parsed['episode_number']}] [Audio: {$parsed['audio_type']}]\n";
    if ($anime) {
        echo "Result : {$status} -> ID {$anime->id} ({$anime->title})\n";
    } else {
        echo "Result : {$status}\n";
    }
    echo "---------------------------------------------------------\n";
}

echo "Total: " . count($testTitles) . " | Pass: {$pass} | Fail: " . (count($testTitles) - $pass) . "\n";
