// SPDX-License-Identifier: MIT
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public class Entry { public string path; public string sha256; public long size; }
public class Manifest { public string version; public string payload_sha256; public string archive_sha256; public string decoder_sha256; public List<Entry> files; public List<Entry> originals; }
public class Change { public string path; public string before; public string after; }
public class Journal { public string game; public string status; public List<Change> changes; }

public static class PatchEngine {
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=16000000 };
    public static readonly string Package=AppDomain.CurrentDomain.BaseDirectory;
    public static string ReadResource(string name) { using(var s=Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) using(var r=new StreamReader(s,Encoding.UTF8)) return r.ReadToEnd(); }
    public static Manifest Load() { return Json.Deserialize<Manifest>(ReadResource("manifest.json")); }
    public static string Hash(string file) { using(var f=File.OpenRead(file)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(f)).Replace("-", ""); }
    public static string Safe(string root,string relative) {
        if(String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(":") || relative.Split('/','\\').Any(x=>x==".." || x=="." || x.Length==0 || x.EndsWith(".") || x.EndsWith(" "))) throw new Exception("허용되지 않은 패치 경로: "+relative);
        string full=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
        if(!full.StartsWith(root.TrimEnd('\\')+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("패치 경로가 게임 폴더를 벗어났습니다.");
        for(string p=full; !String.IsNullOrEmpty(p); p=Path.GetDirectoryName(p)) if((File.Exists(p)||Directory.Exists(p)) && (File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0) throw new Exception("링크/접합점 경로는 지원하지 않습니다: "+p);
        return full;
    }
    public static void WriteJson(string p,object value) {
        string tmp=p+".shivers-"+Guid.NewGuid().ToString("N");
        try {
            byte[] data=new UTF8Encoding(false).GetBytes(Json.Serialize(value));
            using(var stream=new FileStream(tmp,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { stream.Write(data,0,data.Length); stream.Flush(true); }
            if(File.Exists(p)) File.Replace(tmp,p,null); else File.Move(tmp,p);
        } finally { if(File.Exists(tmp)) File.Delete(tmp); }
    }
    static void Put(string source,string target) {
        Directory.CreateDirectory(Path.GetDirectoryName(target));
        string temporary=target+".shivers-"+Guid.NewGuid().ToString("N");
        try { File.Copy(source,temporary); if(File.Exists(target)) File.Replace(temporary,target,null); else File.Move(temporary,target); }
        finally { if(File.Exists(temporary)) File.Delete(temporary); }
    }
    public static void Recover(string root,string backup) {
        if(Process.GetProcesses().Any(p=>p.ProcessName.StartsWith("scummvm",StringComparison.OrdinalIgnoreCase))) throw new Exception("게임/ScummVM을 종료한 다음 복구해 주세요.");
        root=Path.GetFullPath(root).TrimEnd('\\');
        backup=Path.GetFullPath(backup).TrimEnd('\\');
        string parent=Safe(root,"_shivers_ko_backups");
        if(Path.GetDirectoryName(backup)!=parent) throw new Exception("해당 게임의 패치 백업 폴더만 복구할 수 있습니다.");
        Safe(root,backup.Substring(root.Length+1));
        string jp=Safe(backup,"journal.json");
        var j=Json.Deserialize<Journal>(File.ReadAllText(jp,Encoding.UTF8));
        if(!String.Equals(j.game,root,StringComparison.OrdinalIgnoreCase)) throw new Exception("백업의 게임 경로가 다릅니다.");
        if(j.status=="rolled_back") return;
        var allowed=new HashSet<string>(Load().files.Select(e=>e.path),StringComparer.OrdinalIgnoreCase);
        allowed.Add("ShiversKorean.ttf"); allowed.Add("_shivers_ko/install.json");
        if(j.changes==null || j.changes.Select(c=>c.path).Distinct(StringComparer.OrdinalIgnoreCase).Count()!=j.changes.Count || j.changes.Any(c=>!allowed.Contains(c.path))) throw new Exception("허용된 패치 파일 목록과 다른 백업입니다.");
        // Refuse to overwrite subsequent player edits, including after an interrupted apply.
        foreach(var c in j.changes) {
            string p=Safe(root,c.path); string now=File.Exists(p)?Hash(p):null;
            if(now!=c.before && now!=c.after) throw new Exception("패치 이후 변경된 파일이 있어 자동 복구를 중단합니다: "+c.path);
            if(c.before!=null && Hash(Safe(backup,"files/"+c.path))!=c.before) throw new Exception("백업 무결성 오류: "+c.path);
        }
        foreach(var c in j.changes.AsEnumerable().Reverse()) {
            string p=Safe(root,c.path);
            if((File.Exists(p)?Hash(p):null)==c.before) continue;
            if(c.before==null) { if(File.Exists(p)) File.Delete(p); }
            else Put(Safe(backup,"files/"+c.path),p);
        }
        j.status="rolled_back"; WriteJson(jp,j);
    }
    public static string Apply(string root,string saveDirectory,Action<string> log,int failAfter) {
        var m=Load(); root=Path.GetFullPath(root).TrimEnd('\\');
        if(!Environment.Is64BitOperatingSystem || !Directory.Exists(root) || root==Path.GetPathRoot(root).TrimEnd('\\')) throw new Exception("Windows 64비트의 쓰기 가능한 게임 폴더를 선택해 주세요.");
        Safe(root,"RESSCI.000");
        if(Package.StartsWith(root+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("배포 프로그램은 게임 폴더 밖에서 실행해 주세요.");
        if(Process.GetProcesses().Any(p=>p.ProcessName.StartsWith("scummvm",StringComparison.OrdinalIgnoreCase))) throw new Exception("실행 중인 ScummVM을 먼저 종료해 주세요. 프로그램이 게임을 강제 종료하지는 않습니다.");
        log("원본 버전과 게임 데이터 검사 중...");
        foreach(var e in m.originals) { string p=Safe(root,e.path); if(!File.Exists(p)||new FileInfo(p).Length!=e.size||Hash(p)!=e.sha256) throw new Exception("지원 원본과 다르거나 파일이 없습니다: "+e.path+"\n영문 Windows 1.02 원본 데이터를 준비해 주세요."); }
        string backups=Safe(root,"_shivers_ko_backups");
        if(Directory.Exists(backups)) foreach(string folder in Directory.GetDirectories(backups)) {
            string jp=Safe(root,Path.GetFileName(backups)+"/"+Path.GetFileName(folder)+"/journal.json");
            if(File.Exists(jp)) { var j=Json.Deserialize<Journal>(File.ReadAllText(jp)); if(j.status!="complete"&&j.status!="rolled_back") throw new Exception("완료되지 않은 패치가 있습니다. '백업 복구'로 먼저 복구해 주세요:\n"+folder); }
        }
        string font=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Fonts),"malgun.ttf");
        if(!File.Exists(font)) throw new Exception("Windows에 맑은 고딕이 없습니다. 한국어 글꼴 기능을 설치한 후 다시 시도해 주세요.");
        string decoder=Path.Combine(Package,"xdelta3decode.exe"), payload=Path.Combine(Package,"patch.xdelta");
        if(Hash(decoder)!=m.decoder_sha256 || Hash(payload)!=m.payload_sha256) throw new Exception("배포 파일이 손상됐습니다. ZIP을 다시 풀어 주세요.");
        string state=Safe(root,"_shivers_ko/install.json");
        if(String.IsNullOrWhiteSpace(saveDirectory) && File.Exists(state)) saveDirectory=Json.Deserialize<Dictionary<string,string>>(File.ReadAllText(state))["save_directory"];
        if(String.IsNullOrWhiteSpace(saveDirectory)) saveDirectory=Safe(root,"_shivers_ko/saves");
        saveDirectory=Path.GetFullPath(saveDirectory).TrimEnd('\\');
        if(saveDirectory.IndexOfAny(new[]{'\r','\n','\"'})>=0) throw new Exception("잘못된 저장 경로입니다.");
        if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<1024L*1024*1024) throw new Exception("안전한 적용/백업을 위해 여유 공간 1GB 이상이 필요합니다.");
        string stage=Safe(root,"_shivers_ko_stage_"+Guid.NewGuid().ToString("N"));
        string backup=Safe(root,"_shivers_ko_backups/"+DateTime.Now.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N").Substring(0,8));
        bool journalReady=false;
        Directory.CreateDirectory(stage);
        try {
            string archive=Safe(stage,"payload.zip");
            var psi=new ProcessStartInfo(decoder,"-d -s \""+Safe(root,"RESSCI.000")+"\" \""+payload+"\" \""+archive+"\"");
            psi.UseShellExecute=false; psi.CreateNoWindow=true; psi.RedirectStandardError=true; psi.EnvironmentVariables.Remove("XDELTA");
            log("차분 패치를 복원하고 결과를 검사합니다...");
            using(var process=Process.Start(psi)) { string error=process.StandardError.ReadToEnd(); process.WaitForExit(); if(process.ExitCode!=0) throw new Exception("xdelta 적용 실패: "+error); }
            if(Hash(archive)!=m.archive_sha256) throw new Exception("복원된 패치 데이터의 해시가 다릅니다.");
            string ready=Safe(stage,"ready"); Directory.CreateDirectory(ready);
            var expected=m.files.ToDictionary(e=>e.path,StringComparer.OrdinalIgnoreCase);
            using(var zip=ZipFile.OpenRead(archive)) {
                var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach(var e in zip.Entries) {
                    Entry entry; if(!expected.TryGetValue(e.FullName,out entry)||!seen.Add(e.FullName)||e.Length!=entry.size) throw new Exception("예상하지 않은 ZIP 항목: "+e.FullName);
                    string p=Safe(ready,e.FullName); Directory.CreateDirectory(Path.GetDirectoryName(p)); e.ExtractToFile(p);
                    if(Hash(p)!=entry.sha256) throw new Exception("패치 파일 무결성 오류: "+e.FullName);
                }
                if(seen.Count!=expected.Count) throw new Exception("패치 파일이 누락됐습니다.");
            }
            File.Copy(font,Safe(ready,"ShiversKorean.ttf"));
            WriteJson(Safe(ready,"_shivers_ko/install.json"),new Dictionary<string,string>{{"version",m.version},{"save_directory",saveDirectory},{"font_source","Windows installed Malgun Gothic"}});
            var changes=new List<Change>();
            foreach(string p in Directory.GetFiles(ready,"*",SearchOption.AllDirectories).OrderBy(x=>x)) {
                string relative=p.Substring(ready.Length+1).Replace('\\','/');
                string target=Safe(root,relative); if(Directory.Exists(target)) throw new Exception("파일 위치에 폴더가 있습니다: "+relative);
                changes.Add(new Change{path=relative,before=File.Exists(target)?Hash(target):null,after=Hash(p)});
            }
            log("기존 패치 대상 파일을 백업합니다. 세이브 파일은 변경하지 않습니다.");
            Directory.CreateDirectory(backup);
            foreach(var c in changes) if(c.before!=null) { string p=Safe(backup,"files/"+c.path); Directory.CreateDirectory(Path.GetDirectoryName(p)); File.Copy(Safe(root,c.path),p); if(Hash(p)!=c.before) throw new Exception("백업 검증 실패"); }
            var journal=new Journal{game=root,status="prepared",changes=changes};
            WriteJson(Safe(backup,"journal.json"),journal); journalReady=true;
            int count=0;
            foreach(var c in changes) {
                string target=Safe(root,c.path);
                if((File.Exists(target)?Hash(target):null)!=c.before) throw new Exception("적용 중 다른 프로그램이 파일을 변경했습니다: "+c.path);
                Put(Safe(ready,c.path),target);
                if(Hash(target)!=c.after) throw new Exception("적용 결과 불일치: "+c.path);
                count++; if(failAfter>0 && count==failAfter) throw new Exception("QA: 의도적인 중간 실패");
            }
            journal.status="complete"; WriteJson(Safe(backup,"journal.json"),journal);
            log("적용 완료. Shivers Korean.exe로 실행하세요.\n백업: "+backup);
            return backup;
        } catch(Exception original) {
            if(journalReady) try { Recover(root,backup); log("중간 실패: 변경 파일을 적용 전 상태로 복구했습니다."); }
            catch(Exception recovery) { throw new Exception(original.Message+"\n자동 복구 미완료: "+recovery.Message+"\n백업 보존: "+backup); }
            throw;
        } finally {
            // Owned random staging directory only; refuse any injected reparse point.
            if(Directory.Exists(stage)) {
                foreach(string p in Directory.GetFileSystemEntries(stage,"*",SearchOption.AllDirectories)) Safe(stage,p.Substring(stage.Length+1));
                Directory.Delete(stage,true);
            }
        }
    }
}

class PatcherForm:Form {
    TextBox game=new TextBox(), saves=new TextBox(), log=new TextBox(); Button apply=new Button(), recover=new Button(); bool busy;
    public PatcherForm() {
        Text="쉬버스 1 한글 패치 설치"; Font=new Font("Malgun Gothic",10); ClientSize=new Size(790,690); MinimumSize=new Size(720,650); StartPosition=FormStartPosition.CenterScreen; AutoScaleMode=AutoScaleMode.Dpi;
        var layout=new TableLayoutPanel{Dock=DockStyle.Fill,Padding=new Padding(18),ColumnCount=3,RowCount=8};
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,150)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,90));
        Controls.Add(layout);
        var title=new Label{Text="쉬버스 1 · 한글 패치",AutoSize=true,Font=new Font(Font,FontStyle.Bold),Margin=new Padding(0,0,0,12)}; layout.Controls.Add(title,0,0); layout.SetColumnSpan(title,3);
        var guide=new TextBox{Multiline=true,ReadOnly=true,TabStop=false,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,Text=PatchEngine.ReadResource("guide.txt").Replace("\r\n","\n").Replace("\n","\r\n")}; layout.Controls.Add(guide,0,1); layout.SetColumnSpan(guide,3); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,40)); layout.RowStyles.Add(new RowStyle(SizeType.Percent,55));
        layout.Controls.Add(new Label{Text="게임 데이터 폴더",AutoSize=true},0,2); game.Dock=DockStyle.Fill; layout.Controls.Add(game,1,2); var browse=new Button{Text="찾아보기",AutoSize=true}; browse.Click+=(s,e)=>Browse(game); layout.Controls.Add(browse,2,2);
        layout.Controls.Add(new Label{Text="기존 저장 폴더\n(선택)",AutoSize=true},0,3); saves.Dock=DockStyle.Fill; layout.Controls.Add(saves,1,3); var saveBrowse=new Button{Text="찾아보기",AutoSize=true}; saveBrowse.Click+=(s,e)=>Browse(saves); layout.Controls.Add(saveBrowse,2,3);
        var hint=new Label{Text="저장 폴더를 비우면 기존 패치 설정을 유지하거나 게임 폴더 안에 새 저장 위치를 사용합니다.",AutoSize=true,Margin=new Padding(0,8,0,8)}; layout.Controls.Add(hint,0,4); layout.SetColumnSpan(hint,3);
        var buttons=new FlowLayoutPanel{AutoSize=true,Dock=DockStyle.Fill}; apply.Text="패치 적용"; apply.AutoSize=true; apply.Click+=async(s,e)=>await Apply(); recover.Text="백업 복구"; recover.AutoSize=true; recover.Click+=async(s,e)=>await Recover(); buttons.Controls.Add(apply); buttons.Controls.Add(recover); layout.Controls.Add(buttons,0,5); layout.SetColumnSpan(buttons,3);
        log.Multiline=true; log.ReadOnly=true; log.ScrollBars=ScrollBars.Vertical; log.Dock=DockStyle.Fill; layout.Controls.Add(log,0,6); layout.SetColumnSpan(log,3);
        for(int i=2;i<6;i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize)); layout.RowStyles.Add(new RowStyle(SizeType.Percent,45));
        FormClosing+=(s,e)=>{ if(busy) { e.Cancel=true; MessageBox.Show("적용/복구가 끝날 때까지 기다려 주세요."); } };
        Shown+=(s,e)=>{guide.Select(0,0); ActiveControl=game;};
    }
    void Browse(TextBox box) { using(var dialog=new FolderBrowserDialog{Description="폴더를 선택하세요",SelectedPath=Directory.Exists(box.Text)?box.Text:""}) if(dialog.ShowDialog()==DialogResult.OK) box.Text=dialog.SelectedPath; }
    void Log(string s) { if(InvokeRequired) { BeginInvoke(new Action<string>(Log),s); return; } log.AppendText(s+Environment.NewLine); }
    void Busy(bool value) { busy=value; apply.Enabled=recover.Enabled=game.Enabled=saves.Enabled=!value; }
    async Task Apply() {
        if(!Directory.Exists(game.Text)) { MessageBox.Show("게임 데이터 폴더를 먼저 선택해 주세요."); return; }
        string root=game.Text, save=saves.Text;
        if(save.Length>0 && !Directory.Exists(save)) { MessageBox.Show("기존 저장 폴더가 없습니다. 경로를 확인하거나 비워 주세요."); return; }
        Busy(true); try { await Task.Run(()=>PatchEngine.Apply(root,save,Log,0)); MessageBox.Show("패치 적용이 완료됐습니다.\n게임 폴더의 Shivers Korean.exe로 실행하세요.",Text); } catch(Exception e) { Log(e.Message); MessageBox.Show(e.Message,"적용 실패",MessageBoxButtons.OK,MessageBoxIcon.Error); } finally { Busy(false); }
    }
    async Task Recover() {
        if(!Directory.Exists(game.Text)) { MessageBox.Show("게임 폴더를 먼저 선택해 주세요."); return; }
        using(var d=new FolderBrowserDialog{Description="게임 폴더의 _shivers_ko_backups 아래 날짜별 백업을 선택하세요"}) {
            if(d.ShowDialog()!=DialogResult.OK) return;
            if(MessageBox.Show("이 패치가 변경한 파일만 적용 전으로 복구합니다. 계속할까요?","백업 복구",MessageBoxButtons.YesNo)!=DialogResult.Yes) return;
            string root=game.Text, backup=d.SelectedPath; Busy(true); try { await Task.Run(()=>PatchEngine.Recover(root,backup)); Log("복구 완료. 세이브는 변경하지 않았습니다."); } catch(Exception e) { Log(e.Message); } finally { Busy(false); }
        }
    }
}
class Program {
    [STAThread] static int Main(string[] args) {
        if(args.Length>0) {
            try {
                if(args[0]=="--apply" && args.Length>=2) { string saves=""; int fail=0; for(int i=2;i<args.Length;i+=2) { if(args[i]=="--saves") saves=args[i+1]; else if(args[i]=="--fail-after") fail=Int32.Parse(args[i+1]); else throw new Exception("Unknown option"); } PatchEngine.Apply(args[1],saves,Console.WriteLine,fail); }
                else if(args[0]=="--restore" && args.Length==3) PatchEngine.Recover(args[1],args[2]);
                else throw new Exception("Usage: --apply GAME [--saves SAVES] or --restore GAME BACKUP");
                return 0;
            } catch(Exception e) { Console.Error.WriteLine(e.ToString()); return 1; }
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false); Application.Run(new PatcherForm()); return 0;
    }
}
