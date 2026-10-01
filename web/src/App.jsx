import { useEffect, useState } from "react";
import TopNav from "./components/TopNav.jsx";
import PipelineStepper from "./components/PipelineStepper.jsx";
import VendorCompletenessList from "./components/VendorCompletenessList.jsx";
import ProjectPicker from "./screens/ProjectPicker.jsx";
import ReportWindow from "./windows/ReportWindow.jsx";
import RulesWindow from "./windows/RulesWindow.jsx";
import ScoringWindow from "./windows/ScoringWindow.jsx";
import StageIWindow from "./windows/StageIWindow.jsx";
import StageIIWindow from "./windows/StageIIWindow.jsx";
import {
  getActingUser,
  getProject,
  getSettings,
  listProjects,
  listRulesetVersions,
  REPLAY,
  REPLAY_LABEL,
  setActingUser,
  signedInName,
  USE_MOCK,
} from "./api.js";
import { lastStep, rememberStep } from "./projectStage.js";

// Until per-user sessions arrive (checklist item B9) the API takes the acting user from
// X-User. Behind the hosted demo's sign-in, the signed-in person's name is the default, and
// the Rules window can switch it, so one visitor can confirm a rule set as the second person.
export default function App() {
  const [projects, setProjects] = useState(null);
  const [projectId, setProjectId] = useState(null);
  const [hosted, setHosted] = useState(false);
  const [user, setUser] = useState(getActingUser());

  useEffect(() => {
    listProjects().then(setProjects).catch(() => setProjects([]));
    if (USE_MOCK || REPLAY) return;
    getSettings()
      .then((s) => setHosted(Boolean(s.hosted_demo)))
      .catch(() => {});
    signedInName().then((name) => {
      if (!name || import.meta.env?.VITE_API_USER) return;
      setActingUser(name);
      setUser(name);
    });
  }, []);

  // A project made a moment ago isn't in the list read at start: read it again.
  const open = (pid) => {
    listProjects().then(setProjects).catch(() => {});
    setProjectId(pid);
  };

  if (!projectId) {
    return <ProjectPicker onSelect={open} />;
  }

  return (
    <AppShell
      projectId={projectId}
      project={projects?.find((p) => p.id === projectId)}
      onChangeProject={() => setProjectId(null)}
      user={user}
      hosted={hosted}
    />
  );
}

function AppShell({ projectId, project, onChangeProject, user, hosted }) {
  // A project reopens at the step it was left on; the project list shows that step.
  const [activeWindow, setActiveWindow] = useState(() => lastStep(projectId) ?? "rules");
  // null = no tenderer picked yet: the Stage I step shows the bid list, the
  // tenderer's own page once one is picked. Stage II falls back to the first
  // tenderer, the single-tenderer assumption it always had.
  const [tenderer, setTenderer] = useState(null);
  const [bidders, setBidders] = useState([]);
  const [tierFilter, setTierFilter] = useState("all");
  const [tierCounts, setTierCounts] = useState(null);
  // Fail-closed: every step past the rules needs a confirmed rule set
  // (POST /checks answers 409 unconfirmed_ruleset without one).
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setConfirmed(false);
    setTenderer(null);
    listRulesetVersions(projectId)
      .then((versions) => !cancelled && setConfirmed(versions.some((v) => v.status === "confirmed")))
      .catch(() => {});
    getProject(projectId)
      .then((p) => !cancelled && setBidders(p.bidders ?? []))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => rememberStep(projectId, activeWindow), [projectId, activeWindow]);

  const effectiveTenderer = tenderer ?? bidders[0];

  return (
    <div className="app-shell">
      <TopNav
        tenderName={project?.name ?? projectId}
        dataClass={project?.data_class}
        mock={USE_MOCK}
        replay={REPLAY ? REPLAY_LABEL : null}
        onChangeProject={onChangeProject}
        user={user}
      />
      <PipelineStepper
        tierFilter={tierFilter}
        onTierFilter={activeWindow === "rules" ? setTierFilter : null}
        tierCounts={activeWindow === "rules" ? tierCounts : null}
        activeWindow={activeWindow}
        onSelectWindow={setActiveWindow}
        confirmed={confirmed}
      />
      <main className="app-main">
        {activeWindow === "rules" && (
          <RulesWindow
            projectId={projectId}
            tierFilter={tierFilter}
            onCountsChange={setTierCounts}
            onConfirmed={() => setConfirmed(true)}
            allowActAs={hosted}
          />
        )}
        {activeWindow === "stage1" &&
          (tenderer ? (
            <div className="flex-1 flex flex-col overflow-hidden min-h-0">
              <button
                type="button"
                onClick={() => setTenderer(null)}
                className="font-mono text-xs text-accent hover:underline cursor-pointer text-left px-3 py-2
                  border-b border-border bg-bg shrink-0 w-fit"
              >
                ← All tenderers
              </button>
              <StageIWindow projectId={projectId} tenderer={tenderer} />
            </div>
          ) : (
            <VendorCompletenessList projectId={projectId} onSelectVendor={setTenderer} />
          ))}
        {activeWindow === "stage2" && effectiveTenderer && (
          <StageIIWindow projectId={projectId} tenderer={effectiveTenderer} />
        )}
        {/* Scoring and Report are across every tenderer, so neither takes one. */}
        {activeWindow === "scoring" && <ScoringWindow projectId={projectId} />}
        {activeWindow === "report" && <ReportWindow projectId={projectId} />}
      </main>
    </div>
  );
}
