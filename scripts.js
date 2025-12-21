  // ⚠️ تنظیمات
        const CONFIG = {
            username: 'arazshah',
            repo: 'self',
            branch: 'master',
            postsFolder: 'posts',
            imagesFolder: 'images'
        };

        const postsGrid = document.getElementById('posts-grid');
        const postView = document.getElementById('post-view');
        const postContent = document.getElementById('post-content');

        // دریافت لیست فایل‌های MD
        async function loadPosts() {
            try {
                const path = CONFIG.postsFolder ? `/${CONFIG.postsFolder}` : '';
                const apiUrl = `https://api.github.com/repos/${CONFIG.username}/${CONFIG.repo}/contents${path}?ref=${CONFIG.branch}`;

                const response = await fetch(apiUrl);
                if (!response.ok) throw new Error('خطا در دریافت فایل‌ها');

                const files = await response.json();
                const mdFiles = files.filter(f => f.name.endsWith('.md'));

                if (mdFiles.length === 0) {
                    postsGrid.innerHTML = '<div class="error">هیچ فایل MD یافت نشد</div>';
                    return;
                }

                const posts = mdFiles.slice(0, 32);

                // ساخت URL برای thumbnail از پوشه images
                const imagesBase = `https://raw.githubusercontent.com/${CONFIG.username}/${CONFIG.repo}/${CONFIG.branch}/${CONFIG.imagesFolder}`;

                postsGrid.innerHTML = posts.map(file => {
                    const baseName = file.name.replace('.md', '');
                    const thumbUrl = `${imagesBase}/${baseName}.png`;
                    const title = formatTitle(file.name);

                    return `
                        <div class="post-card" onclick="loadPost('${file.download_url}', '${file.name}')">
                            <div class="post-thumb">
                                <img src="${thumbUrl}" alt="${baseName}" onerror="this.src='https://via.placeholder.com/300x150?text=No+Image'">
                            </div>
                            <h3>${title}</h3>
                        </div>
                    `;
                }).join('');

            } catch (error) {
                postsGrid.innerHTML = `<div class="error">خطا: ${error.message}</div>`;
            }
        }

        // تبدیل نام فایل به عنوان خوانا
        function formatTitle(filename) {
            return filename
                .replace('.md', '')
                .replace(/-/g, ' ')
                .replace(/_/g, ' ');
        }

        // بارگذاری و نمایش یک پست
        async function loadPost(url, filename) {
            postContent.innerHTML = '<div class="loading">در حال بارگذاری...</div>';
            postsGrid.classList.add('hidden');
            postView.classList.add('active');

            try {
                const response = await fetch(url);
                if (!response.ok) throw new Error('خطا در دریافت محتوا');

                const markdown = await response.text();
                postContent.innerHTML = marked.parse(markdown);

            } catch (error) {
                postContent.innerHTML = `<div class="error">خطا: ${error.message}</div>`;
            }
        }

        // بازگشت به لیست
        function goBack() {
            postView.classList.remove('active');
            postsGrid.classList.remove('hidden');
        }

        // شروع
        loadPosts();