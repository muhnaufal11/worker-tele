import json
import re
import subprocess
import sys

def norm_title(t):
    t = (t or '').lower()
    t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', t)
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return ' '.join(t.split())

def main():
    print("Fetching live completed state from nipnime-app container...")
    cmd = [
        "ssh", "naufal@192.168.100.65",
        "docker exec nipnime-app php -r \"require __DIR__ . '/vendor/autoload.php'; "
        "$app = require_once __DIR__ . '/bootstrap/app.php'; "
        "$kernel = $app->make(Illuminate\\Contracts\\Console\\Kernel::class); "
        "$kernel->bootstrap(); "
        "$page = new App\\Filament\\Pages\\OngoingWatcherMonitor(); "
        "$page->completedFilter = 'all'; "
        "$res = $page->getCompletedState(true); "
        "echo json_encode($res['items']);\""
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("SSH STDERR:", e.stderr)
        print("SSH STDOUT:", e.stdout)
        raise e
    items = json.loads(res.stdout.strip())
    print(f"Loaded {len(items)} items from monitor.")

    state_path = "z:/tools/terop-worker/.completed_anime_state.json"
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    queue = state.get("queue", [])
    history = state.get("history", {})

    # Map existing queue items by norm title
    q_by_norm = {}
    for q in queue:
        q_norm = norm_title(q.get("title", ""))
        q_by_norm[q_norm] = q

    new_queue = []
    seen = set()

    complete_count = 0
    in_progress_count = 0
    pending_count = 0

    for it in items:
        title = it.get("title", "")
        n_title = norm_title(title)
        st = it.get("status", "pending")

        # Find in existing queue or construct
        orig_q = q_by_norm.get(n_title, {})
        merged = dict(orig_q)
        merged["title"] = title
        merged["status"] = st
        if it.get("slug"):
            merged["slug"] = it.get("slug")

        if st == "complete":
            history[n_title] = "complete"
            complete_count += 1
        else:
            if n_title in history:
                del history[n_title]
            if st == "in_progress":
                in_progress_count += 1
            else:
                pending_count += 1

        if n_title not in seen:
            new_queue.append(merged)
            seen.add(n_title)

    # Append any remaining queue items that were not in items
    for q in queue:
        n_title = norm_title(q.get("title", ""))
        if n_title not in seen:
            new_queue.append(q)
            seen.add(n_title)

    state["queue"] = new_queue
    state["history"] = history

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"Sync complete! Total queue: {len(new_queue)}")
    print(f"Stats: Complete: {complete_count}, In Progress: {in_progress_count}, Pending: {pending_count}")
    print(f"Top 5 queue items:")
    for i, q in enumerate(new_queue[:5]):
        print(f"  {i+1}. {q.get('title')} [{q.get('status')}]")

if __name__ == "__main__":
    main()
