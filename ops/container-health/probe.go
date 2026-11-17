// Static Linux probe for images without a shell (including Portainer).
package main

import (
 "crypto/tls"
 "fmt"
 "io"
 "net"
 "net/http"
 "os"
 "path/filepath"
 "strconv"
 "strings"
 "time"
)
func check(args []string) error {
 if len(args)<2 { return fmt.Errorf("expected probe type and target") }
 switch args[0] {
 case "http", "https-local":
  tr:=&http.Transport{Proxy:nil, TLSClientConfig:&tls.Config{InsecureSkipVerify:args[0]=="https-local"}}
  // Self-signed TLS is accepted only for an explicitly selected loopback URL.
  if args[0]=="https-local" && !strings.HasPrefix(args[1],"https://127.0.0.1:") {return fmt.Errorf("TLS exception requires loopback")}
  c:=&http.Client{Transport:tr,Timeout:5*time.Second}
  r,e:=c.Get(args[1]); if e!=nil{return fmt.Errorf("HTTP probe failed")};defer r.Body.Close()
  if r.StatusCode<200 || r.StatusCode>=400{return fmt.Errorf("HTTP status %d",r.StatusCode)}
  _,e=io.Copy(io.Discard,io.LimitReader(r.Body,4096));return e
 case "tcp":
  c,e:=net.DialTimeout("tcp",args[1],5*time.Second);if e!=nil{return fmt.Errorf("TCP probe failed")};return c.Close()
 case "redis":
  c,e:=net.DialTimeout("tcp",args[1],5*time.Second);if e!=nil{return fmt.Errorf("Redis connection failed")};defer c.Close();c.SetDeadline(time.Now().Add(5*time.Second))
  if _,e=c.Write([]byte("*1\r\n$4\r\nPING\r\n"));e!=nil{return e};b:=make([]byte,512);n,e:=c.Read(b);if e!=nil{return e}
  s:=string(b[:n]);if !strings.HasPrefix(s,"+PONG") && !strings.HasPrefix(s,"-NOAUTH"){return fmt.Errorf("Redis did not respond to PING")};return nil
 case "process":
  es,e:=os.ReadDir("/proc");if e!=nil{return e}
  for _,v:=range es {n,e:=strconv.Atoi(v.Name());if e!=nil || n==os.Getpid(){continue};b,_:=os.ReadFile(filepath.Join("/proc",v.Name(),"cmdline"));s:=strings.ReplaceAll(string(b),"\x00"," ");if strings.Contains(s,args[1]){return nil}}
  return fmt.Errorf("expected worker process missing")
 }
 return fmt.Errorf("unknown probe")
}
func main(){if e:=check(os.Args[1:]);e!=nil{fmt.Fprintln(os.Stderr,e);os.Exit(1)}}
