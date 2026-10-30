[目次へ戻る](README.md)

# SSM Agent の役割とフットプリント

AWS Systems Manager Agent（SSM Agent）は、EC2 などの管理対象に常駐し、AWS Systems Manager からの指示を受けて実行するソフトウェア。Session Manager による接続や Run Command の実行などに使う。[AWS 公式：SSM Agent](https://docs.aws.amazon.com/systems-manager/latest/userguide/ssm-agent.html)

ここでは Linux の EC2 を中心に、SSM Agent の役割と、メモリ・CPU の見積もりに使える公開例をまとめる。

## 主な役割と動作

| 機能 | SSM Agent が行うこと |
| --- | --- |
| Session Manager | 管理者がインスタンスへ接続するためのセッションを処理する |
| Run Command | 指定されたコマンドやスクリプトの実行を処理する |
| State Manager など | 関連付けられた設定や操作を処理する |

Agent は Systems Manager のエンドポイントと通信し、指示や実行結果をやり取りする。利用には Agent の稼働に加え、適切な IAM 権限と通信経路が必要。プライベートサブネットでは、NAT または必要な VPC エンドポイントを含めて通信経路を設計する。[AWS 公式：VPC エンドポイントを使用した Systems Manager の設定](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-create-vpc.html)

Linux では `amazon-ssm-agent` のほか、`ssm-agent-worker` が動作する構成がある。セッションやコマンドの実行時は、さらに処理用の子プロセスやシェルが起動する。そのため、親プロセスだけの RSS と、サービス全体のメモリは異なる。[AWS 公式：worker のトラブルシューティング](https://repost.aws/knowledge-center/systems-manager-crash-reasons)

## メモリ使用量の公開例

**以下は個別の表示例・運用報告であり、AWS の標準値や保証値ではない。** OS、Agent のバージョン、起動後の時間、処理内容、測定範囲が異なるため、直接の性能比較はできない。

| 公開例 | 報告されたメモリ | 対象・状況 |
| --- | ---: | --- |
| AWS 公式ドキュメントの表示例 | 34.6M | `systemctl status` のサービスの cgroup。親プロセスと worker を含む。測定環境・負荷の詳細は不明。[AWS の RHEL 向け手順](https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-rhel-8-9.html) |
| APC 技術ブログ・2024 年 | 63.4M | RHEL 9・x86-64 で Agent を起動して約 20 秒後のサービスの cgroup。親プロセスと worker を含む。[導入事例](https://techblog.ap-com.co.jp/entry/2024/05/17/093000) |
| DevelopersIO・2023 年 | 263.8M | Session Manager 接続中のサービスの cgroup。Agent のほかセッション用 worker やシェルも含む。[検証記事](https://dev.classmethod.jp/articles/linux-ssm-session-manager-env-var/) |
| ECS Fargate の運用報告・2024 年 | 約 239 MiB | ECS Exec 用の `amazon-ssm-agent` 単一プロセスの RSS。`GOGC=off` などの環境変数が影響した特殊な事例。[調査記事](https://qiita.com/gacha-ru/items/612d25fa8ed3be12180c) |

`systemctl status` の `Memory` はサービスの cgroup に属する使用量で、単一プロセスの RSS とは異なる。cgroup のメモリには、プロセスのメモリのほか、カーネルによるファイルキャッシュなども計上され得る。[Linux カーネル：cgroup v2 のメモリ](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html#memory)

ECS Exec の SSM Agent はコンテナ内でアプリと一緒に動く。上表の Fargate の報告を EC2 ホストの常駐量へそのまま流用しない。AWS も ECS Exec の CPU・メモリをタスクの資源配分に含めるよう案内している。[AWS 公式：ECS Exec](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html)

## 30 台での見積もり

例えば、各台でサービス全体が 63.4 MiB だったと仮定すると、30 台では次の計算になる。

```text
63.4 MiB × 30 台 ÷ 1,024 ≒ 1.86 GiB
```

これは公開例を単純に掛けた参考値で、Ubuntu や Amazon Linux の ARM64 環境で測定した値ではない。前表の `63.4M` を MiB 相当として概算している。

[30 台規模のアプリサーバー最適化](app-server-optimization.md) のホスト常駐分(OS)には SSM Agent と CloudWatch Agent を含めている。SSM Agent を別枠で詳細化するときは、その分をホスト常駐分(OS)から分けて計上し、二重に足さない。

EC2 の搭載メモリを超えないように、Agent だけでなく OS、監視エージェント、アプリ、負荷時の増加と運用余裕も含めて各台で判断する。

## 実機で確認する

### サービス全体

インストール方式によってサービス名が異なる。[AWS 公式：Agent の状態確認](https://docs.aws.amazon.com/systems-manager/latest/userguide/ssm-agent-status-and-restart.html)

```bash
# Amazon Linux などで一般的なサービス名
systemctl status amazon-ssm-agent

# Ubuntu で Snap 版を使う場合
systemctl status snap.amazon-ssm-agent.amazon-ssm-agent
```

`Memory` と、表示される cgroup 内のプロセスを確認する。Session Manager で接続中なら、セッション用の worker やシェルが含まれる場合がある。

### プロセスごとの RSS

```bash
ps -eo pid,ppid,rss,args | grep -E '[a]mazon-ssm-agent|[s]sm-agent-worker|[s]sm-session-worker|[s]sm-document-worker'
```

`RSS` 列は KiB。親 Agent、常駐 worker、セッションやコマンド用 worker をそれぞれ確認できる。この一覧には、Agent が起動したシェルや任意のコマンドなど、名前が一致しない子プロセスは含まれない。プロセス間の共有ページは重複するため、RSS の単純合計は参考値として扱う。

起動時の値だけで判断せず、次の状態を比較する。

1. 起動処理が落ち着き、セッションやコマンドを実行していない状態。
2. Session Manager で接続している状態。
3. Run Command や Agent 更新を実行している状態と、その終了後。
4. Agent のバージョン更新後と、一定期間稼働した後。

CPU は、今回の公開例から安定時の一般的な使用率を判断できない。`systemctl status` に表示される CPU 時間は累積値であり、そのまま現在の CPU 使用率ではない。継続監視には CloudWatch Agent の `procstat` で、プロセスの `memory_rss` や `cpu_usage` を収集できる。[AWS 公式：procstat](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-procstat-process-metrics.html)
