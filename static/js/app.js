document.addEventListener("DOMContentLoaded", () => {
    const searchForm    = document.getElementById("searchForm");
    const lyricsInput   = document.getElementById("lyricsInput");
    const countrySelect = document.getElementById("countrySelect");
    const genreSelect   = document.getElementById("genreSelect");
    const searchBtn     = document.getElementById("searchBtn");
    const btnText       = document.getElementById("searchBtnText");
    const btnLoad       = document.getElementById("searchBtnLoading");
    const grid          = document.getElementById("resultsGrid");
    const resultsInfo   = document.getElementById("resultsInfo");
    const resultsCount  = document.getElementById("resultsCount");
    const resultsQuery  = document.getElementById("resultsQuery");
    const filterNotice  = document.getElementById("filterNotice");
    const statusMsg     = document.getElementById("statusMessage");
    const emptyState    = document.getElementById("emptyState");
    const clearBtn      = document.getElementById("clearBtn");

    const artistCache = {};

    loadCountries();
    loadGenres();

    searchForm.addEventListener("submit", (e) => { e.preventDefault(); performSearch(); });
    clearBtn.addEventListener("click", clearResults);

    async function loadCountries() {
        try {
            const data = await (await fetch("/api/countries")).json();
            countrySelect.innerHTML = "";
            data.forEach((c) => addOption(countrySelect, c.code, c.name));
        } catch { countrySelect.innerHTML = '<option value="">Select country...</option>'; }
    }

    async function loadGenres() {
        try {
            const data = await (await fetch("/api/genres")).json();
            genreSelect.innerHTML = '<option value="">Select genre...</option>';
            data.forEach((g) => addOption(genreSelect, g.name, g.name));
        } catch { genreSelect.innerHTML = '<option value="">Select genre...</option>'; }
    }

    function addOption(sel, val, label) {
        const o = document.createElement("option");
        o.value = val; o.textContent = label;
        sel.appendChild(o);
    }

    async function performSearch() {
        const query = lyricsInput.value.trim();
        if (!query) { showStatus("Enter lyrics keywords to search.", "error"); return; }

        const country = countrySelect.value;
        const genre = genreSelect.value;
        const hasFilters = country || genre;

        setLoading(true, hasFilters);
        hideStatus(); hide(resultsInfo); hide(emptyState); hide(filterNotice);
        grid.innerHTML = "";
        showSkeletons();

        const params = new URLSearchParams({ q: query });
        if (country) params.set("country", country);
        if (genre) params.set("genre", genre);

        try {
            const data = await (await fetch(`/api/search?${params}`)).json();
            grid.innerHTML = "";

            if (data.error) { showStatus(data.error, "error"); show(emptyState); setLoading(false); return; }

            if (!data.tracks?.length) {
                showStatus(hasFilters
                    ? "No songs found with those filters. Try different keywords or broader filters."
                    : "No songs found. Try different keywords.", "info");
                show(emptyState); setLoading(false); return;
            }

            resultsCount.textContent = data.tracks.length;
            const displayQuery = query.length > 60 ? query.slice(0, 57) + "…" : query;
            resultsQuery.textContent = `"${displayQuery}"`;
            show(resultsInfo);

            if (hasFilters) {
                const parts = [];
                if (country) parts.push(countrySelect.options[countrySelect.selectedIndex]?.textContent || country);
                if (genre) parts.push(genre);
                filterNotice.textContent = `Filtered by ${parts.join(" + ")}`;
                show(filterNotice);
            }

            data.tracks.forEach((t, i) => grid.appendChild(makeCard(t, i, data.filtered)));
            setLoading(false);

            if (!data.filtered) {
                filterNotice.textContent = "Showing top global results. Select a country or genre to find music from a specific region.";
                show(filterNotice);
                enrichArtists(data.tracks);
            }
        } catch {
            showStatus("Something went wrong. Please try again.", "error");
            show(emptyState); setLoading(false);
        }
    }

    // ── Lazy artist enrichment ──────────────────────────────────

    async function enrichArtists(tracks) {
        for (const name of [...new Set(tracks.map((t) => t.artist_name))]) {
            if (!artistCache[name]?.loaded) {
                try {
                    const info = await (await fetch(`/api/artist-info?name=${encodeURIComponent(name)}`)).json();
                    artistCache[name] = { ...info, loaded: true };
                } catch { artistCache[name] = { country_code: "", country_name: "", genres: [], loaded: true }; }
            }
            patchCards(name);
        }
    }

    function patchCards(name) {
        const info = artistCache[name];
        if (!info) return;
        document.querySelectorAll(`[data-artist="${CSS.escape(name)}"]`).forEach((card) => {
            const bc = card.querySelector(".track-card__badges");
            if (!bc) return;
            const ld = bc.querySelector(".badge-loading"); if (ld) ld.remove();
            if (info.country_code && !bc.querySelector(".badge-country")) {
                bc.insertAdjacentHTML("afterbegin",
                    `<span class="badge badge-country">${esc(countryName(info.country_code) || info.country_name || info.country_code)}</span>`);
            }
            if (!bc.querySelector(".badge-genre") && info.genres?.length) {
                info.genres.slice(0, 3).forEach((g) =>
                    bc.insertAdjacentHTML("beforeend", `<span class="badge badge-genre">${esc(g)}</span>`));
            }
        });
    }

    // ── Card builder ────────────────────────────────────────────

    function makeCard(track, idx, pre) {
        const card = document.createElement("div");
        card.className = "track-card fade-in";
        card.style.animationDelay = `${idx * 35}ms`;
        card.dataset.artist = track.artist_name;

        const src = track.album_art || "";
        const artCls = src ? "track-card__art" : "track-card__art track-card__art--placeholder";
        const artInner = src
            ? `<img src="${src}" alt="" loading="lazy">`
            : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-3v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="15" r="3"/></svg>`;

        let badges = "";
        if (pre) {
            if (track.artist_country || track.artist_country_name)
                badges += `<span class="badge badge-country">${esc(countryName(track.artist_country) || track.artist_country_name || track.artist_country)}</span>`;
            (track.genres || []).slice(0, 3).forEach((g) =>
                badges += `<span class="badge badge-genre">${esc(g)}</span>`);
        } else {
            badges = `<span class="badge-loading">Loading…</span>`;
        }

        const date = track.release_date ? `<span class="track-card__date">${esc(track.release_date)}</span>` : "";
        const link = track.genius_url
            ? `<a href="${track.genius_url}" target="_blank" rel="noopener" class="track-card__link">
                   Genius <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
               </a>` : "";

        card.innerHTML = `
            <div class="${artCls}">${artInner}</div>
            <div class="track-card__body">
                <span class="track-card__title">${esc(track.track_name)}</span>
                <span class="track-card__artist">${esc(track.artist_name)}</span>
                ${date}
                <div class="track-card__badges">${badges}</div>
                ${link}
            </div>`;
        return card;
    }

    // ── Skeletons ───────────────────────────────────────────────

    function showSkeletons() {
        grid.innerHTML = "";
        for (let i = 0; i < 8; i++) {
            const el = document.createElement("div");
            el.className = "track-card";
            el.style.opacity = ".45";
            el.innerHTML = `
                <div class="skeleton" style="width:56px;height:56px;border-radius:var(--r2);flex-shrink:0"></div>
                <div class="track-card__body" style="gap:6px">
                    <div class="skeleton" style="height:13px;width:65%"></div>
                    <div class="skeleton" style="height:11px;width:40%"></div>
                    <div style="display:flex;gap:4px;margin-top:6px">
                        <div class="skeleton" style="height:16px;width:44px;border-radius:60px"></div>
                        <div class="skeleton" style="height:16px;width:56px;border-radius:60px"></div>
                    </div>
                </div>`;
            grid.appendChild(el);
        }
    }

    // ── Helpers ──────────────────────────────────────────────────

    function setLoading(on, filters) {
        searchBtn.disabled = on;
        btnText.classList.toggle("hidden", on);
        btnLoad.classList.toggle("hidden", !on);
        const t = btnLoad.querySelector("span:last-child");
        if (t) t.textContent = on && filters ? "Searching & verifying…" : "Searching…";
    }

    function showStatus(msg, type) {
        statusMsg.textContent = msg;
        statusMsg.className = `status status--${type}`;
    }
    function hideStatus() { statusMsg.className = "status hidden"; }

    function show(el) { el.classList.remove("hidden", "empty--hidden", "bar--hidden"); }
    function hide(el) { el.classList.add("hidden"); }

    function clearResults() {
        grid.innerHTML = "";
        hide(resultsInfo); hide(filterNotice); hideStatus();
        show(emptyState);
        lyricsInput.value = ""; countrySelect.value = ""; genreSelect.value = "";
        lyricsInput.focus();
    }

    function countryName(code) {
        if (!code) return "";
        const m = [...countrySelect.options].find((o) => o.value.toUpperCase() === code.toUpperCase());
        return m ? m.textContent : "";
    }

    function esc(text) {
        const d = document.createElement("div");
        d.textContent = text || "";
        return d.innerHTML;
    }
});
