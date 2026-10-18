<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Http\Controllers\Api\TeropWorkerController;
use App\Models\Anime;

$controller = new TeropWorkerController();

$jsonFile = __DIR__ . '/muse_playlists.json';
if (!file_exists($jsonFile)) {
    echo "muse_playlists.json tidak ditemukan!\n";
    exit(1);
}

$playlists = json_decode(file_get_contents($jsonFile), true);

$results = [
    'matched' => [],
    'unmatched' => [],
];

$reflection = new ReflectionClass($controller);
$findMethod = $reflection->getMethod('findMatchingAnime');
$findMethod->setAccessible(true);

$uniqueTitles = [];
foreach ($playlists as $pl) {
    $rawTitle = $pl['title'] ?? '';
    // Skip playlist koleksi/event
    if (preg_match('/(semua episode|kolaborasi|film.*seru|koleksi|anime festival)/iu', $rawTitle)) {
        continue;
    }

    $parsed = $controller->parseYouTubeTitle($rawTitle);
    $clean = $parsed['clean_title'];
    if (!isset($uniqueTitles[$clean])) {
        $uniqueTitles[$clean] = [
            'raw' => $rawTitle,
            'parsed' => $parsed,
            'playlist_id' => $pl['id'] ?? '',
        ];
    }
}

echo "=========================================================\n";
echo "MENGUJI PENCOCOKAN " . count($uniqueTitles) . " JUDUL UNIK MUSE INDONESIA\n";
echo "=========================================================\n\n";

foreach ($uniqueTitles as $cleanTitle => $info) {
    $parsed = $info['parsed'];
    $match = $findMethod->invoke(
        $controller,
        $parsed['clean_title'],
        $parsed['season'],
        $parsed['part'],
        $parsed['franchise_hint']
    );

    if ($match && !empty($match['anime'])) {
        $anime = $match['anime'];
        $results['matched'][] = [
            'clean' => $cleanTitle,
            'audio_type' => $parsed['audio_type'],
            'matched_id' => $anime->id,
            'matched_title' => $anime->title,
            'confidence' => $match['confidence'] ?? 1.0,
        ];
    } else {
        $results['unmatched'][] = [
            'clean' => $cleanTitle,
            'raw' => $info['raw'],
            'audio_type' => $parsed['audio_type'],
            'parsed' => $parsed,
        ];
    }
}

$total = count($uniqueTitles);
$matchedCount = count($results['matched']);
$unmatchedCount = count($results['unmatched']);
$pct = round(($matchedCount / $total) * 100, 1);

echo "HASIL SEMENTARA:\n";
echo "Total Judul Unik    : {$total}\n";
echo "Berhasil Dicocokkan : {$matchedCount} ({$pct}%)\n";
echo "Belum Cocok         : {$unmatchedCount}\n\n";

if ($unmatchedCount > 0) {
    echo "---------------------------------------------------------\n";
    echo "DAFTAR JUDUL YANG BELUM COCOK:\n";
    echo "---------------------------------------------------------\n";
    foreach ($results['unmatched'] as $idx => $u) {
        $num = $idx + 1;
        echo "{$num}. Clean: \"{$u['clean']}\"\n";
        echo "   Raw  : \"{$u['raw']}\"\n";
        echo "   Audio: [{$u['audio_type']}]\n";
    }
}

file_put_contents(__DIR__ . '/unmatched_report.json', json_encode($results['unmatched'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
