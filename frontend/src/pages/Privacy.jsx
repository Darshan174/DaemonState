import { Link } from "react-router-dom";

import DaemonStateIcon from "../components/DaemonStateIcon";
import "./LandingReplica.css";
import "./Privacy.css";


export default function Privacy() {
  return (
    <div className="dsr-landing dsr-privacy">
      <header className="dsr-privacy-header">
        <Link to="/" aria-label="DaemonState home" className="dsr-brand">
          <DaemonStateIcon size={29} />
          <span>DaemonState</span>
        </Link>
        <Link to="/#early-access" className="dsr-privacy-back">
          Return to early access
        </Link>
      </header>

      <main>
        <article>
          <p className="dsr-privacy-kicker">PUBLIC WAITLIST / PRIVACY</p>
          <h1>Privacy notice</h1>
          <p className="dsr-privacy-effective">Effective August 3, 2026</p>

          <p className="dsr-privacy-lead">
            This notice covers the DaemonState public website and early-access
            waitlist. DaemonState&apos;s self-hosted product stores project data in
            the environment chosen by its operator; that product data is not part
            of this public waitlist.
          </p>

          <section>
            <h2>Information collected</h2>
            <p>
              When you join, we store your email address, the campaign parameters
              attached to the page URL, the referring site and path, and the time
              and version of the consent notice you accepted. Query strings and
              fragments are removed from referrer URLs before storage.
            </p>
            <p>
              We may later add information you voluntarily provide, such as your
              role, team size, coding tools, and the context problem you want to
              solve. The waitlist record can also contain operational fields such
              as invitation status, contact history, and internal notes.
            </p>
          </section>

          <section>
            <h2>How the information is used</h2>
            <p>
              We use waitlist information to manage private-beta access, send
              requested product updates, understand which launch channels work,
              select useful design partners, and improve onboarding. We do not
              sell waitlist information.
            </p>
          </section>

          <section>
            <h2>Service providers</h2>
            <p>
              Cloudflare hosts the public site and D1 waitlist database. When
              configured, Loops delivers waitlist email and PostHog receives a
              small set of manually defined website events. The analytics setup
              does not send your email address, disables session replay and
              autocapture, and keeps its browser identifier in memory only.
            </p>
          </section>

          <section>
            <h2>Retention and your choices</h2>
            <p>
              We keep a waitlist record while early access is operating or while
              it is reasonably needed for beta communication. You can unsubscribe
              using the link in an email. You can also ask for access, correction,
              or deletion by contacting the repository owner privately through
              the contact method on the owner&apos;s GitHub profile. Do not put your
              email address or other personal information in a public issue.
            </p>
            <a
              href="https://github.com/Darshan174"
              target="_blank"
              rel="noreferrer"
              className="dsr-privacy-contact"
            >
              Contact the repository owner
            </a>
          </section>

          <section>
            <h2>Changes to this notice</h2>
            <p>
              Material changes will be reflected on this page with a new effective
              date. The consent version stored with new signups is updated when the
              waitlist notice changes.
            </p>
          </section>
        </article>
      </main>

      <footer className="dsr-privacy-footer">
        <span>© 2026 DaemonState</span>
        <Link to="/">daemonstate.com</Link>
      </footer>
    </div>
  );
}
