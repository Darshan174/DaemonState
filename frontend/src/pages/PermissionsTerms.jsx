import { Link } from "react-router-dom";

import DaemonStateIcon from "../components/DaemonStateIcon";
import "./LandingReplica.css";
import "./PermissionsTerms.css";


const PUBLIC_GITHUB_REPOSITORY = "https://github.com/Darshan174/DaemonState";
const PUBLIC_LICENSE = `${PUBLIC_GITHUB_REPOSITORY}/blob/main/LICENSE`;


export default function PermissionsTerms() {
  return (
    <div className="dsr-landing dsr-terms">
      <header className="dsr-terms-header">
        <Link to="/" aria-label="DaemonState home" className="dsr-brand">
          <DaemonStateIcon size={29} />
          <span>DaemonState</span>
        </Link>
        <nav aria-label="Legal navigation" className="dsr-terms-header-nav">
          <Link to="/privacy">Privacy</Link>
          <Link to="/#early-access">Return to early access</Link>
        </nav>
      </header>

      <main>
        <div className="dsr-terms-layout">
          <div className="dsr-terms-hero">
            <p className="dsr-terms-kicker">
              <span aria-hidden="true" />
              PRODUCT / TOOLKIT TERMS
            </p>
            <h1 aria-label="Permissions & terms">
              Permissions
              <span>&amp; terms</span>
            </h1>
            <p className="dsr-terms-version">
              PROPRIETARY PRODUCT / PUBLIC TOOLKIT SUL-1.0
            </p>
            <div className="dsr-terms-actions">
              <a
                href={PUBLIC_LICENSE}
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-primary"
              >
                Read toolkit license <span aria-hidden="true">↗</span>
              </a>
              <a
                href={PUBLIC_GITHUB_REPOSITORY}
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-secondary"
              >
                View public toolkit <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <article>
            <header className="dsr-terms-intro">
              <p>
                DaemonState is proprietary software. The DaemonState engine,
                production application, hosted services, and other non-public
                components may be used only under the applicable DaemonState
                product or commercial terms.
              </p>
              <aside>
                This page is a plain-language guide. The terms supplied with a
                DaemonState product or service control that offering. The
                published <a
                  href={PUBLIC_LICENSE}
                  target="_blank"
                  rel="noreferrer"
                >
                  SUL-1.0 license
                </a> controls the separately distributed public toolkit.
              </aside>
            </header>

            <section>
              <p className="dsr-terms-section-label">LICENSING MAP</p>
              <h2>The terms follow what you receive</h2>
              <ul>
                <li>
                  The private engine, production application, hosted services,
                  and other non-public components are proprietary.
                </li>
                <li>
                  A packaged Free product is governed by the DaemonState product
                  terms supplied with it; free access does not make the private
                  product source-available.
                </li>
                <li>
                  Paid access is governed by the applicable commercial,
                  subscription, or other written terms.
                </li>
                <li>
                  Only the public integration and demonstration toolkit on
                  GitHub is separately licensed under SUL-1.0.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label">PUBLIC TOOLKIT</p>
              <h2>What SUL-1.0 permits</h2>
              <p>
                For the public toolkit only, the license permits personal and
                noncommercial use and a company&apos;s internal business use. It
                also permits you to:
              </p>
              <ul>
                <li>
                  Study, audit, copy, and adapt the toolkit for those permitted
                  uses.
                </li>
                <li>
                  Share original or modified toolkit copies free of charge for
                  noncommercial purposes while keeping the required terms and
                  notices with them.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label is-restricted">NOT INCLUDED</p>
              <h2>Commercial toolkit uses need permission</h2>
              <p>The public toolkit&apos;s SUL-1.0 license does not let you:</p>
              <ul>
                <li>Sell toolkit copies or paid distributions.</li>
                <li>White-label the toolkit as a commercial product.</li>
                <li>Operate it as a paid hosted or managed service for others.</li>
                <li>
                  Sell access to its functionality or make the toolkit a
                  substantial source of value in a paid customer offering.
                </li>
              </ul>
              <p>
                A different commercial use requires separate written permission
                from every copyright holder whose work is included.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">CONDITIONS</p>
              <h2>Keep the notices with the toolkit</h2>
              <ul>
                <li>
                  Anyone receiving a toolkit copy must also receive the license
                  terms.
                </li>
                <li>
                  Do not remove or obscure license, copyright, or other licensor
                  notices.
                </li>
                <li>
                  Mark modified copies with a prominent notice that you changed
                  the software.
                </li>
                <li>
                  No trademark or other rights are granted unless the license
                  says so.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label">PATENTS / TERMINATION</p>
              <h2>SUL permission depends on compliance</h2>
              <p>
                For the public toolkit, the patent grant follows the same SUL
                limits and ends if you or your company make a written patent
                claim covered by the license. Use outside the terms is unlicensed
                and automatically terminates the SUL license.
              </p>
              <p>
                After notice of a first violation, stopping every violation
                within 30 days reinstates the license retroactively. A later
                violation after reinstatement terminates it permanently.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">NO WARRANTY</p>
              <h2>The public toolkit is provided as is</h2>
              <p>
                As far as the law allows, the public toolkit comes without
                warranty or condition, and its licensors are not liable for
                damages arising from the SUL terms or from the use or nature of
                the toolkit. Any product or service warranty is governed by its
                own applicable terms.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">HISTORICAL RELEASES</p>
              <h2>Earlier license grants are preserved</h2>
              <p>
                Certain historical software published by the project, including
                code released under the MIT License, remains governed by the
                license that accompanied those copies. Those grants are not
                retroactively revoked, but they do not apply to current or future
                DaemonState software unless expressly stated.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">OTHER COMPONENTS</p>
              <h2>Third-party terms still apply</h2>
              <p>
                Third-party software and fonts keep their own licenses. They are
                not covered by DaemonState product terms or by the public
                toolkit&apos;s SUL-1.0 grant. Review the
                {" "}<a href="/assets/legal/THIRD_PARTY_NOTICES.txt">
                  third-party notices
                </a> before redistributing the product.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">PRIVACY / QUESTIONS</p>
              <h2>Need clarity or a different permission?</h2>
              <p>
                Waitlist data is handled under the <Link to="/privacy">privacy
                notice</Link>. For product terms, a commercial toolkit exception,
                or a use near a license boundary, get legal advice or written
                permission instead of relying on this summary.
              </p>
              <a
                href="https://github.com/Darshan174"
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-contact"
              >
                Contact the repository owner <span aria-hidden="true">↗</span>
              </a>
            </section>
          </article>
        </div>
      </main>

      <footer className="dsr-terms-footer">
        <span>© 2026 DaemonState</span>
        <div>
          <Link to="/privacy">Privacy notice</Link>
          <a href={PUBLIC_GITHUB_REPOSITORY} target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
