import { useEffect, useState } from "react";
import TopNav from "./components/TopNav.jsx";
import PipelineStepper from "./components/PipelineStepper.jsx";
import VendorCompletenessList from "./components/VendorCompletenessList.jsx";
import Login from "./screens/Login.jsx";
import ProjectPicker from "./screens/ProjectPicker.jsx";
import Window1 from "./windows/Window1.jsx";
import Window2 from "./windows/Window2.jsx";
import Window2b from "./windows/Window2b.jsx";
import Window3 from "./windows/Window3.jsx";
import Window4 from "./windows/Window4.jsx";
import { getCurrentUser, getRequirementsConfirmation, listTenders, logout, stage1RtmCsvUrl } from "./api.js";

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = still checking, null = logged out
  const [tenders, setTenders] = useState(null);
  const [tenderId, setTenderId] = useState(null);
  const [activeWindow, setActiveWindow] = useState("window1");
  // null = no vendor picked yet - Window2 (Completeness Check) shows the
  // vendor list landing page in that state, the existing per-vendor detail
  // page once one is picked. Window2b/Window3 aren't gated by this list (not
  // asked for), so they fall back to the tender's first vendor when this is
  // still null, same single-vendor assumption they already had.
  const [vendorId, setVendorId] = useState(null);

  useEffect(() => {
    getCurrentUser().then((data) => setUser(data?.user ?? null));
  }, []);

  useEffect(() => {
    if (user) {
      listTenders().then(setTenders);
    }
  }, [user]);

  useEffect(() => {
    setVendorId(null);
  }, [tenderId]);

  function handleChangeProject() {
    setTenderId(null);
    setActiveWindow("window1");
  }

  function handleLogout() {
    logout().then(() => {
      setUser(null);
      setTenders(null);
      setTenderId(null);
    });
  }

  if (user === undefined) {
    return <div className="window-status">Checking session…</div>;
  }
  if (!user) {
    return <Login onLoggedIn={setUser} />;
  }
  if (!tenderId) {
    return <ProjectPicker onSelect={setTenderId} />;
  }

  const activeTender = tenders?.find((t) => t.id === tenderId);

  return (
    <AppShell
      tenderId={tenderId}
      vendorId={vendorId}
      setVendorId={setVendorId}
      activeTender={activeTender}
      activeWindow={activeWindow}
      setActiveWindow={setActiveWindow}
      handleChangeProject={handleChangeProject}
      handleLogout={handleLogout}
      user={user}
    />
  );
}

function AppShell({
  tenderId,
  vendorId,
  setVendorId,
  activeTender,
  activeWindow,
  setActiveWindow,
  handleChangeProject,
  handleLogout,
  user,
}) {
  // window2b/Window3 aren't gated behind the vendor list (only window2 -
  // Completeness Check - was asked for), so they keep the same "just use the
  // tender's first vendor" behavior they always had when nothing's been
  // explicitly picked via window2 yet.
  const effectiveVendorId = vendorId ?? activeTender?.vendors?.[0]?.id;
  // The tier filter lives here rather than in Window1 because it renders in the
  // stage bar, alongside the pipeline switcher - matching the reference design,
  // where the phase switcher and its filter share one row. Window1 owns the data,
  // so it reports the counts back up.
  const [tierFilter, setTierFilter] = useState("all");
  const [tierCounts, setTierCounts] = useState(null);
  // Fail-closed default: until this tender's real confirmation state has
  // loaded, treat it as unconfirmed so the gate below never flashes open
  // before we actually know. Lives here (not in Window1) so PipelineStepper
  // can gate on it too - Window1 reads/writes it via props instead of
  // polling its own copy, so there's one source of truth per tender.
  const [confirmation, setConfirmation] = useState({ confirmed: false, reviewer: null, confirmed_at: null });

  useEffect(() => {
    let cancelled = false;
    setConfirmation({ confirmed: false, reviewer: null, confirmed_at: null });
    getRequirementsConfirmation(tenderId)
      .then((data) => {
        if (!cancelled) setConfirmation(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [tenderId]);

  return (
    <div className="app-shell">
      <TopNav
        tenderName={activeTender?.name}
        onChangeProject={handleChangeProject}
        onLogout={handleLogout}
        user={user}
      />
      <PipelineStepper
        tierFilter={tierFilter}
        onTierFilter={activeWindow === "window1" ? setTierFilter : null}
        tierCounts={activeWindow === "window1" ? tierCounts : null}
        rtmCsvUrl={activeWindow === "window1" ? stage1RtmCsvUrl(tenderId) : null}
        activeWindow={activeWindow}
        onSelectWindow={setActiveWindow}
        confirmed={confirmation.confirmed}
      />
      <main className="app-main">
        {activeWindow === "window1" && (
          <Window1
            tenderId={tenderId}
            tierFilter={tierFilter}
            onCountsChange={setTierCounts}
            confirmation={confirmation}
            onConfirmationChange={setConfirmation}
          />
        )}
        {activeWindow === "window2" &&
          (vendorId ? (
            <div className="flex-1 flex flex-col overflow-hidden min-h-0">
              <button
                type="button"
                onClick={() => setVendorId(null)}
                className="font-mono text-xs text-accent hover:underline cursor-pointer text-left px-3 py-2
                  border-b border-border bg-bg shrink-0 w-fit"
              >
                ← All vendors
              </button>
              <Window2 tenderId={tenderId} vendorId={vendorId} />
            </div>
          ) : (
            <VendorCompletenessList tenderId={tenderId} onSelectVendor={setVendorId} />
          ))}
        {activeWindow === "window2b" && effectiveVendorId && <Window2b tenderId={tenderId} vendorId={effectiveVendorId} />}
        {activeWindow === "window3" && <Window3 tenderId={tenderId} />}
        {activeWindow === "window4" && <Window4 tenderId={tenderId} />}
      </main>
    </div>
  );
}
