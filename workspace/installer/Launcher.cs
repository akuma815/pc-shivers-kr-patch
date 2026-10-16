// SPDX-License-Identifier: MIT
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Launcher {
    static string Hash(string p) { using (var f=File.OpenRead(p)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(f)).Replace("-", ""); }
    [STAThread] static int Main(string[] args) {
        try {
            string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string managed=Path.Combine(root,"_shivers_ko");
            var state=new JavaScriptSerializer().Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(managed,"install.json"),Encoding.UTF8));
            string runner=Path.Combine(managed,"runtime",RuntimeIdentity.Name);
            if(Hash(runner)!=RuntimeIdentity.Hash) throw new Exception("전용 실행 파일이 없거나 변경됐습니다. 한글 패치를 다시 적용해 주세요.");
            string font=Path.Combine(root,"ShiversKorean.ttf");
            if(!File.Exists(font)) throw new Exception("맑은 고딕 파일이 없습니다. 패치를 다시 적용해 주세요.");
            string saves=state["save_directory"];
            if(saves.IndexOfAny(new[]{'\r','\n','\"'})>=0 || !Path.IsPathRooted(saves)) throw new Exception("저장 경로가 올바르지 않습니다.");
            Directory.CreateDirectory(saves);
            string config=Path.Combine(managed,"scummvm.ini");
            // Preserve other private settings, but force the two subtitle-related domains.
            var sections=new Dictionary<string,Dictionary<string,string>>(StringComparer.OrdinalIgnoreCase);
            string section="scummvm";
            sections[section]=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            if(File.Exists(config)) foreach(string raw in File.ReadAllLines(config)) {
                string line=raw.Trim();
                if(line.StartsWith("[") && line.EndsWith("]")) {
                    section=line.Substring(1,line.Length-2);
                    if(!sections.ContainsKey(section)) sections[section]=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
                } else { int n=line.IndexOf('='); if(n>0) sections[section][line.Substring(0,n).Trim()]=line.Substring(n+1).Trim(); }
            }
            if(!sections.ContainsKey("shivers-ko-full")) sections["shivers-ko-full"]=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            sections["scummvm"]["subtitles"]="false";
            var game=sections["shivers-ko-full"];
            game["gameid"]="shivers"; game["platform"]="windows"; game["language"]="ko";
            game["subtitles"]="false"; game["path"]=root; game["savepath"]=saves;
            game["description"]="Shivers Korean";
            var text=new StringBuilder();
            foreach(var pair in sections) { text.AppendLine("["+pair.Key+"]"); foreach(var kv in pair.Value) text.AppendLine(kv.Key+"="+kv.Value); text.AppendLine(); }
            File.WriteAllText(config,text.ToString(),new UTF8Encoding(false));
            if(args.Length==1 && args[0]=="--prepare-only") return 0;
            bool resume=args.Length==1 && args[0]=="--continue";
            if(args.Length>0 && !resume) throw new Exception("지원하지 않는 실행 옵션입니다.");
            if(resume && !File.Exists(Path.Combine(saves,"shivers-ko-full.001"))) throw new Exception("1번 저장이 없습니다. 일반 실행 후 Old Game에서 저장을 선택해 주세요.");
            var start=new ProcessStartInfo(runner,"--config=\""+config+"\" --path=\""+root+"\" --savepath=\""+saves+"\" --opl-driver=nuked --no-subtitles --language=ko "+(resume?"--save-slot=1 ":"")+"shivers-ko-full");
            start.UseShellExecute=false; start.WorkingDirectory=root;
            Process.Start(start); return 0;
        } catch(Exception e) { if(Array.IndexOf(args,"--prepare-only")<0) MessageBox.Show(e.Message,"쉬버스 한글판 실행 오류",MessageBoxButtons.OK,MessageBoxIcon.Error); return 1; }
    }
}
