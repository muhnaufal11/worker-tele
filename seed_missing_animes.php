<?php
require __DIR__ . '/../../vendor/autoload.php';
$app = require_once __DIR__ . '/../../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

use App\Models\Anime;

$missing = [
    [
        'title' => 'Kaijuu Caramelise',
        'title_en' => 'Kaiju Girl Caramelise',
        'slug' => 'kaiju-girl-caramelise',
        'synopsis' => 'Kuroe Akaishi menderita penyakit langka di mana luapan emosinya mengubah dirinya menjadi monster Kaiju raksasa.',
        'type' => 'ONA',
        'status' => 'Ongoing',
        'season' => 'Spring',
        'total_episodes' => 12,
    ],
    [
        'title' => 'Katekyou Hitman Reborn!',
        'title_en' => 'REBORN!',
        'slug' => 'katekyou-hitman-reborn',
        'synopsis' => 'Tsunayoshi Sawada adalah seorang murid SMP biasa yang ceroboh dan dijuluki "Dame Tsuna". Hidupnya berubah 180 derajat saat seorang bayi bernama Reborn datang dari Italia untuk melatihnya menjadi bos ke-10 keluarga mafia Vongola.',
        'type' => 'TV',
        'status' => 'Completed',
        'season' => 'Fall',
        'total_episodes' => 203,
        'mal_id' => 1604,
    ],
    [
        'title' => 'Kore Kaite Shine',
        'title_en' => 'Draw This, Then Die!',
        'slug' => 'kore-kaite-shine',
        'synopsis' => 'Di pulau Izu Oshima, hiduplah siswi SMA pecinta manga bernama Yasumi Ai. Mengikuti kisah kecintaannya dan perjuangannya membuat manga.',
        'type' => 'ONA',
        'status' => 'Ongoing',
        'season' => 'Fall',
        'total_episodes' => 12,
        'mal_id' => 61280,
    ]
];

foreach ($missing as $data) {
    $anime = Anime::firstOrCreate(
        ['slug' => $data['slug']],
        $data
    );
    echo "Anime {$anime->title} (ID: {$anime->id}) ready!\n";
}
