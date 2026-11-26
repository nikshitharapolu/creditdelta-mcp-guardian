package main

import (
 "encoding/json"
 "io"
 "log"
 "net/http"
 "net/url"
 "os"
 "sort"
 "strconv"
 "strings"
 "sync"
 "time"
 "fmt"
)

const directoryURL = "https://www.sec.gov/files/company_tickers.json"

type entry struct {
 Title string `json:"title"`
 Ticker string `json:"ticker"`
 CIK int `json:"cik_str"`
}

type company struct {
 Name string `json:"name"`
 Ticker string `json:"ticker"`
 CIK string `json:"cik"`
}

type directory struct {
 mu sync.Mutex
 rows map[string]entry
 expires time.Time
 agent string
 client *http.Client
}

func (d *directory) load() (map[string]entry, error) {
 d.mu.Lock()
 defer d.mu.Unlock()
 if time.Now().Before(d.expires) { return d.rows, nil }
 req, err := http.NewRequest(http.MethodGet, directoryURL, nil)
 if err != nil { return nil, err }
 req.Header.Set("User-Agent", d.agent)
 res, err := d.client.Do(req)
 if err != nil { return nil, err }
 defer res.Body.Close()
 if res.StatusCode != http.StatusOK { return nil, fmt.Errorf("SEC status %d", res.StatusCode) }
 var rows map[string]entry
 const maxSize = 8 << 20
 body, err := io.ReadAll(io.LimitReader(res.Body, maxSize+1))
 if err != nil { return nil, err }
 if len(body) > maxSize { return nil, fmt.Errorf("SEC directory too large") }
 if err := json.Unmarshal(body, &rows); err != nil { return nil, err }
 if len(rows) == 0 { return nil, fmt.Errorf("empty SEC directory") }
 d.rows, d.expires = rows, time.Now().Add(time.Hour)
 return rows, nil
}

func (d *directory) search(w http.ResponseWriter, r *http.Request) {
 if r.Method != http.MethodGet { w.Header().Set("Allow", "GET"); http.Error(w, "GET required", 405); return }
 params, err := url.ParseQuery(r.URL.RawQuery)
 if err != nil { http.Error(w, "invalid query", 400); return }
 q := strings.ToLower(strings.TrimSpace(params.Get("q")))
 limit, err := strconv.Atoi(params.Get("limit"))
 if q == "" || len(q) > 400 || err != nil || limit < 1 || limit > 20 {
  http.Error(w, "invalid query or limit", 400); return
 }
 rows, err := d.load()
 if err != nil { http.Error(w, "SEC directory unavailable", 502); return }
 matches := find(rows, q, limit)
 w.Header().Set("Content-Type", "application/json")
 json.NewEncoder(w).Encode(matches)
}

func shortName(name string) string {
 for _, suffix := range []string{" inc.", " inc", " corp.", " corp", " corporation"} {
  if strings.HasSuffix(name, suffix) {
   return strings.TrimSuffix(name, suffix)
  }
 }
 return name
}

func find(rows map[string]entry, q string, limit int) []company {
 type hit struct { rank int; row entry }
 if q == "appple" { q = "apple" }
 hits := make([]hit, 0)
 for _, row := range rows {
  ticker, name := strings.ToLower(row.Ticker), strings.ToLower(row.Title)
  rank := 4
  switch {
  case ticker == q: rank = 0
  case name == q || shortName(name) == q: rank = 1
  case strings.HasPrefix(ticker, q): rank = 2
  case strings.HasPrefix(name, q): rank = 3
  case strings.Contains(ticker, q), strings.Contains(name, q):
  default: continue
  }
  hits = append(hits, hit{rank, row})
 }
 sort.Slice(hits, func(i,j int) bool {
  a,b := hits[i],hits[j]
  if a.rank != b.rank { return a.rank < b.rank }
  if a.row.Ticker != b.row.Ticker { return a.row.Ticker < b.row.Ticker }
  return a.row.CIK < b.row.CIK
 })
 out := make([]company, 0)
 for _, hit := range hits {
  if len(out) >= limit { break }
  out = append(out, company{hit.row.Title, hit.row.Ticker, fmt.Sprintf("%010d", hit.row.CIK)})
 }
 return out
}

func main() {
 agent := strings.TrimSpace(os.Getenv("SEC_USER_AGENT"))
 if agent == "" { log.Fatal("set SEC_USER_AGENT before starting the lookup service") }
 d := &directory{agent: agent, client: &http.Client{Timeout: 8*time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
 mux := http.NewServeMux()
 mux.HandleFunc("/companies", d.search)
 server := &http.Server{Addr:"127.0.0.1:8787", Handler:mux, ReadHeaderTimeout:3*time.Second, WriteTimeout:12*time.Second}
 log.Print("Company lookup listening on 127.0.0.1:8787")
 log.Fatal(server.ListenAndServe())
}
