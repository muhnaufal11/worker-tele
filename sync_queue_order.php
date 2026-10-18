<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Filament\Pages\OngoingWatcherMonitor;

$monitor = new OngoingWatcherMonitor();
$res = $monitor->getCompletedState(true);
$items = $res['items'] ?? [];

$stateFile = __DIR__ . '/.completed_anime_state.json';
if (!file_exists($stateFile)) {
    echo "File not found: $stateFile\n";
    exit(1);
}

$raw = json_decode(file_get_contents($stateFile), true) ?: [];
$origQueue = $raw['queue'] ?? [];

$origMap = [];
foreach ($origQueue as $it) {
    $titleKey = strtolower(trim($it['title'] ?? ''));
    if ($titleKey !== '') {
        $origMap[$titleKey] = $it;
    }
}

$sortedQueue = [];
foreach ($items as $mItem) {
    $titleKey = strtolower(trim($mItem['title'] ?? ''));
    if (isset($origMap[$titleKey])) {
        $qItem = $origMap[$titleKey];
        $qItem['pct'] = (int) ($mItem['pct'] ?? 0);
        $qItem['status'] = (string) ($mItem['status'] ?? 'pending');
        $qItem['total_episodes'] = (int) ($mItem['total_eps'] ?? 12);
        $qItem['has_1080p'] = !empty($mItem['has_1080p']);
        if (!empty($mItem['available_resolutions'])) {
            $qItem['available_resolutions'] = $mItem['available_resolutions'];
        }
        if ($qItem['has_1080p'] && is_array($qItem['available_resolutions'] ?? null)) {
            if (!in_array('1080p', $qItem['available_resolutions'])) {
                $qItem['available_resolutions'][] = '1080p';
            }
        }
        // Anti-False Complete: Jika anime masih in_progress (< 100%), jangan biarkan completed_eps berisi penuh
        if ($qItem['status'] === 'in_progress' && count($qItem['completed_eps'] ?? []) >= $qItem['total_episodes']) {
            $qItem['completed_eps'] = [];
        }
        $sortedQueue[] = $qItem;
        unset($origMap[$titleKey]);
    }
}

// Tambahkan sisa item jika ada
foreach ($origMap as $remItem) {
    $sortedQueue[] = $remItem;
}

$raw['queue'] = $sortedQueue;
file_put_contents($stateFile, json_encode($raw, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));

echo "Successfully synchronized " . count($sortedQueue) . " anime in priority order!\n";
foreach (array_slice($sortedQueue, 0, 10) as $i => $q) {
    echo ($i + 1) . ". " . $q['title'] . " | " . $q['status'] . " | Pct: " . $q['pct'] . "%\n";
}
