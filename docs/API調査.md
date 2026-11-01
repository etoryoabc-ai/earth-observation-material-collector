# 公式 API・取得方法の調査

確認日：2026-11-01（日本時間）。以下の公式文書をWeb閲覧で確認。APIエンドポイントの実通信成功を意味しません。個別素材の現在のライセンスは別途確認が必要です。

| 提供元 | 調査資料 | 本版の対応 |
|---|---|---|
| Pexels | https://www.pexels.com/api/documentation/ | 公式の動画・写真検索。Authorizationヘッダー。動画は新しい `/v1/videos/search` を採用。複数解像度は1候補。提供元へのリンク表示。無料キー必須。 |
| Pixabay | https://pixabay.com/api/docs/ | 公式の動画・画像検索。24時間キャッシュ、レート制限で停止。恒久的な画像ホットリンクを避け、プレビューは検索結果として表示。無料キー必須。 |
| Commons | https://www.mediawiki.org/wiki/API:Imageinfo | Action API検索とimageinfo/extmetadata。元ファイルとライセンス情報を取得。認識できないライセンスはD。 |
| NASA | https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf | 公式検索API。素材ページ・メタデータまで、ファイル取得は対象外。 |
| USGS | https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits | 第三者素材もあるため一律自由利用としない。手動確認リンク。自動コネクター未実装。 |
| NPS | https://www.nps.gov/subjects/digital/nps-data-api.htm | 公式APIとキー登録方法が存在。初期版では手動リンクのみでAPI実装未完了。 |
| NOAA | https://www.noaa.gov/multimedia | 素材入口への手動リンクのみ。統一検索APIの採用は未完了。 |

Pexels / Pixabayの利用条件URLも候補に記録します。APIが返すメタデータを利用許諾の最終判断にしません。ソースコードにキーを記録しません。スクレイピング、YouTubeのダウンロード、有料API、制限回避は実装していません。

v1.1：429の待機期限・24時間キャッシュ・提供元別実行予算・Pexelsローカル時間枠予算を追加。一般ライセンスと素材個別確認の記録を分離。残課題：HTTP日付形式のRetry-Afterへの厳密な対応、月次/日次予算管理、NPS等の追加API、プレビュー期限切れ表示の制御。
