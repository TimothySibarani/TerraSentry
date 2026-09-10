import * as cdk from "aws-cdk-lib";

import { TerraSentryStack } from "../lib/terrasentry-stack";

const app = new cdk.App();

new TerraSentryStack(app, "TerraSentry");
