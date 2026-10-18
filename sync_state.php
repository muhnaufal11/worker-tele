<?php

require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

function normalize_title(string $title): string {
    $t = strtolower($title);
    $t = preg_replace('/[\(\[\{].*?[\)\]\}]/', '', $t);
    $t = preg_replace('/[^a-z0-9]+/', ' ', $t);
    return trim(preg_replace('/\s+/', ' ', $t));
}

$statePath = __DIR__ . '/.completed_anime_state.json';
if (!file_exists($statePath)) {
    echo "State file not found at: {$statePath}\n";
    exit(1);
}

$state = json_decode(file_get_contents($statePath), true) ?: [];
$queue = $state['queue'] ?? [];
$history = $state['history'] ?? [];

echo "Existing queue count: " . count($queue) . "\n";
echo "Existing history count: " . count($history) . "\n";

$page = new App\Filament\Pages\OngoingWatcherMonitor();
$page->completedFilter = 'all';
$res = $page->getCompletedState(true);

$items = $res['items'] ?? [];
echo "Fetched " . count($items) . " items from monitor (Done: {$res['total_done']}, Progress: {$res['total_progress']}, Pending: {$res['total_pending']})\n";

// Index existing queue by normalized title
$qByNorm = [];
foreach ($queue as $q) {
    $norm = normalize_title($q['title'] ?? '');
    if ($norm !== '') {
        $qByNorm[$norm] = $q;
    }
}

$newQueue = [];
$seen = [];
$completeCount = 0;
$inProgressCount = 0;
$pendingCount = 0;

foreach ($items as $it) {
    $title = $it['title'] ?? '';
    $norm = normalize_title($title);
    if ($norm === '' || isset($seen[$norm])) {
        continue;
    }
    $seen[$norm] = true;

    $st = $it['status'] ?? 'pending';
    $origQ = $qByNorm[$norm] ?? [];
    $merged = $origQ;
    $merged['title'] = $title;
    $merged['status'] = $st;
    if (!empty($it['slug'])) {
        $merged['slug'] = $it['slug'];
    }

    if ($st === 'complete') {
        $history[$norm] = 'complete';
        $completeCount++;
    } else {
        if (isset($history[$norm])) {
            unset($history[$norm]);
        }
        if ($st === 'in_progress') {
            $inProgressCount++;
        } else {
            $pendingCount++;
        }
    }

    $newQueue[] = $merged;
}

// Append any missing items from old queue
foreach ($queue as $q) {
    $norm = normalize_title($q['title'] ?? '');
    if ($norm !== '' && !isset($seen[$norm])) {
        $seen[$norm] = true;
        $newQueue[] = $q;
    }
}

$state['queue'] = $newQueue;
$state['history'] = $history;

file_put_contents($statePath, json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));

echo "Successfully synchronized state!\n";
echo "Queue size: " . count($newQueue) . " (Complete: {$completeCount}, In Progress: {$inProgressCount}, Pending: {$pendingCount})\n";
echo "History size (true complete): " . count($history) . "\n";
echo "\nTop 10 Focus Anime (In Progress):\n";
$printed = 0;
foreach ($newQueue as $q) {
    if ($q['status'] === 'in_progress') {
        $printed++;
        echo "  {$printed}. {$q['title']} [{$q['status']}]\n";
        if ($printed >= 10) break;
    }
}
